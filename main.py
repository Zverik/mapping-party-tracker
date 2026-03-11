"""
Mapping Party Tracker — FastAPI application entry point.
Run with:  uv run main.py
"""
import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import (
    FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect,
    UploadFile, File, Form, Depends
)
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, FileResponse
)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import database as db
import auth
from ws_manager import manager, claimed_event, released_event, status_event
from geojson_utils import (
    validate_and_extract_features, feature_to_db_text,
    diff_geojson_upload, GeoJSONError
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="Mapping Party Tracker", docs_url=None, redoc_url=None)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests without a matching Origin/Referer header."""
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next):
        if request.method in self.SAFE_METHODS:
            return await call_next(request)
        # Allow WebSocket upgrades
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        base = os.environ.get("BASE_URL", "")
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        if base and origin and not origin.startswith(base):
            return JSONResponse({"error": "CSRF check failed"}, status_code=403)
        return await call_next(request)


app.add_middleware(CSRFMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    db.init_pool()
    db.init_schema()
    auth.init_auth()
    logger.info("Application started")


# ─── HTML pages ───────────────────────────────────────────────────────────────

def _read_template(name: str) -> str:
    return (BASE_DIR / "templates" / name).read_text()


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return HTMLResponse(_read_template("index.html"))


@app.get("/map/{project_id}", response_class=HTMLResponse)
async def map_page(project_id: int, request: Request):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return HTMLResponse(_read_template("map.html"))


@app.get("/edit/{project_id}", response_class=HTMLResponse)
async def edit_page(project_id: int, request: Request):
    user_id = auth.get_current_user_id(request)
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not user_id or user_id != project["owner_id"]:
        raise HTTPException(403, "Only the project owner can edit this project")
    return HTMLResponse(_read_template("edit.html"))


# ─── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def login(request: Request, next: str = "/"):
    return await auth.start_oauth(request, next_url=next)


@app.get("/auth/callback")
async def callback(request: Request):
    osm_info, next_url = await auth.handle_callback(request)
    user = db.upsert_user(osm_info["osm_id"], osm_info["username"])

    session_token = auth.create_session_cookie(user["id"])
    response = RedirectResponse(next_url or "/", status_code=302)
    response.set_cookie(
        "session",
        session_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
        secure=os.environ.get("BASE_URL", "").startswith("https"),
    )
    response.delete_cookie("oauth_state")
    return response


@app.post("/auth/logout")
async def logout(request: Request):
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("session")
    return response


# ─── Session info endpoint ────────────────────────────────────────────────────

@app.get("/api/me")
async def api_me(request: Request):
    user_id = auth.get_current_user_id(request)
    if not user_id:
        return JSONResponse({"authenticated": False})
    user = db.get_user_by_id(user_id)
    if not user:
        return JSONResponse({"authenticated": False})
    return JSONResponse({
        "authenticated": True,
        "id": user["id"],
        "username": user["username"],
        "osm_id": user["osm_id"],
    })


# ─── Project API ──────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def api_list_projects():
    projects = db.list_projects()
    # Convert datetime to str for JSON
    result = []
    for p in projects:
        p = dict(p)
        if p.get("created_at"):
            p["created_at"] = p["created_at"].isoformat()
        result.append(p)
    return JSONResponse(result)


@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    p = dict(project)
    if p.get("created_at"):
        p["created_at"] = p["created_at"].isoformat()
    return JSONResponse(p)


@app.post("/api/projects")
async def api_create_project(
    request: Request,
    title: str = Form(...),
    geojson_file: UploadFile = File(...),
):
    user_id = auth.require_auth(request)

    if not title.strip():
        raise HTTPException(400, "Title is required")

    raw = await geojson_file.read()
    try:
        features = validate_and_extract_features(raw)
    except GeoJSONError as e:
        raise HTTPException(400, str(e))

    project_id = db.create_project(title.strip(), user_id)

    with db.get_db() as conn:
        cursor = conn.cursor()
        for feature in features:
            cursor.execute(
                "INSERT INTO polygons (project_id, geojson, status) VALUES (%s, %s, 0)",
                (project_id, feature_to_db_text(feature)),
            )
        cursor.close()

    return JSONResponse({"id": project_id, "title": title.strip()}, status_code=201)


# ─── Polygon API ──────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/polygons")
async def api_get_polygons(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rows = db.get_polygons_for_project(project_id)
    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "project_id": row["project_id"],
            "geojson": json.loads(row["geojson"]),
            "status": row["status"],
            "claimed_by_id": row["claimed_by_id"],
            "claimed_by_username": row["claimed_by_username"],
        })
    return JSONResponse(result)


@app.post("/api/polygons/{polygon_id}/claim")
async def api_claim_polygon(polygon_id: int, request: Request):
    user_id = auth.require_auth(request)
    polygon = db.get_polygon(polygon_id)
    if not polygon:
        raise HTTPException(404, "Polygon not found")

    project = db.get_project(polygon["project_id"])
    if project["locked"]:
        raise HTTPException(403, "Project is locked")

    # Check user doesn't already have a claim in this project
    existing = db.get_user_active_claim(user_id, polygon["project_id"])
    if existing:
        raise HTTPException(409, "You must release your current polygon first")

    success = db.claim_polygon(polygon_id, user_id)
    if not success:
        raise HTTPException(409, "Polygon is already claimed")

    user = db.get_user_by_id(user_id)
    await manager.broadcast(
        polygon["project_id"],
        claimed_event(polygon_id, user_id, user["username"]),
    )

    return JSONResponse({"ok": True})


@app.post("/api/polygons/{polygon_id}/release")
async def api_release_polygon(polygon_id: int, request: Request):
    user_id = auth.require_auth(request)
    polygon = db.get_polygon(polygon_id)
    if not polygon:
        raise HTTPException(404, "Polygon not found")

    success = db.release_polygon(polygon_id, user_id)
    if not success:
        raise HTTPException(403, "You do not have an active claim on this polygon")

    await manager.broadcast(polygon["project_id"], released_event(polygon_id))

    return JSONResponse({"ok": True})


@app.post("/api/polygons/{polygon_id}/status")
async def api_set_status(polygon_id: int, request: Request):
    user_id = auth.require_auth(request)
    body = await request.json()
    status = body.get("status")
    if status is None or not isinstance(status, int) or status < 0 or status > 5:
        raise HTTPException(400, "status must be an integer 0–5")

    polygon = db.get_polygon(polygon_id)
    if not polygon:
        raise HTTPException(404, "Polygon not found")

    success = db.set_polygon_status(polygon_id, user_id, status)
    if not success:
        raise HTTPException(403, "You do not have an active claim on this polygon")

    await manager.broadcast(polygon["project_id"], status_event(polygon_id, status))

    return JSONResponse({"ok": True})


# ─── Stats API ────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/stats")
async def api_stats(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    stats = db.get_project_stats(project_id)
    return JSONResponse(stats)


# ─── Project edit API ─────────────────────────────────────────────────────────

@app.put("/api/projects/{project_id}")
async def api_update_project(project_id: int, request: Request):
    user_id = auth.require_auth(request)
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project["owner_id"] != user_id:
        raise HTTPException(403, "Only the project owner can edit this project")

    body = await request.json()
    title = str(body.get("title", "")).strip()
    if not title:
        raise HTTPException(400, "Title is required")
    link_url = body.get("link_url") or None
    link_text = body.get("link_text") or None
    locked = bool(body.get("locked", False))

    db.update_project(project_id, title, link_url, link_text, locked)
    return JSONResponse({"ok": True})


@app.post("/api/projects/{project_id}/upload")
async def api_upload_polygons(
    project_id: int,
    request: Request,
    geojson_file: UploadFile = File(...),
    confirm: str = Form(default="false"),
):
    """Upload new GeoJSON to replace project polygons."""
    user_id = auth.require_auth(request)
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project["owner_id"] != user_id:
        raise HTTPException(403, "Only the project owner can upload polygons")

    raw = await geojson_file.read()
    try:
        new_features = validate_and_extract_features(raw)
    except GeoJSONError as e:
        raise HTTPException(400, str(e))

    existing = db.get_all_polygons_raw(project_id)
    diff = diff_geojson_upload(existing, new_features)

    if diff["warnings"] and confirm != "true":
        return JSONResponse({
            "needs_confirm": True,
            "warnings": diff["warnings"],
        })

    # Apply the diff
    with db.get_db() as conn:
        cursor = conn.cursor()
        for poly_id in diff["remove"]:
            cursor.execute("DELETE FROM polygons WHERE id = %s", (poly_id,))
        for feature in diff["add"]:
            cursor.execute(
                "INSERT INTO polygons (project_id, geojson, status) VALUES (%s, %s, 0)",
                (project_id, feature_to_db_text(feature)),
            )
        cursor.close()

    return JSONResponse({
        "ok": True,
        "added": len(diff["add"]),
        "removed": len(diff["remove"]),
        "kept": len(diff["keep"]),
    })


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/projects/{project_id}")
async def ws_endpoint(websocket: WebSocket, project_id: int):
    project = db.get_project(project_id)
    if not project:
        await websocket.close(code=4004)
        return

    await manager.connect(project_id, websocket)
    try:
        while True:
            # Keep connection alive; we only broadcast from server side
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=os.environ.get("DEBUG", "false").lower() == "true",
    )

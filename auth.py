"""OpenStreetMap OAuth2 authentication using Authlib."""
import os
import logging
from authlib.integrations.httpx_client import AsyncOAuth2Client
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

OSM_AUTHORIZE_URL = "https://www.openstreetmap.org/oauth2/authorize"
OSM_TOKEN_URL = "https://www.openstreetmap.org/oauth2/token"
OSM_USER_URL = "https://api.openstreetmap.org/api/0.6/user/details.json"

_serializer: URLSafeTimedSerializer | None = None


def init_auth():
    global _serializer
    secret = os.environ["SESSION_SECRET"]
    _serializer = URLSafeTimedSerializer(secret, salt="session")


def _get_oauth_client() -> AsyncOAuth2Client:
    return AsyncOAuth2Client(
        client_id=os.environ["OSM_CLIENT_ID"],
        client_secret=os.environ["OSM_CLIENT_SECRET"],
        redirect_uri=os.environ["BASE_URL"] + "/auth/callback",
        scope="read_prefs",
    )


async def start_oauth(request: Request, next_url: str = "/") -> RedirectResponse:
    """Redirect user to OSM OAuth2 authorization page."""
    async with _get_oauth_client() as client:
        uri, state = client.create_authorization_url(OSM_AUTHORIZE_URL)

    # Store state + next_url in signed cookie
    payload = {"state": state, "next": next_url}
    signed = _serializer.dumps(payload)

    response = RedirectResponse(uri, status_code=302)
    response.set_cookie(
        "oauth_state",
        signed,
        httponly=True,
        samesite="lax",
        max_age=600,
        secure=os.environ.get("BASE_URL", "").startswith("https"),
    )
    return response


async def handle_callback(request: Request) -> tuple[dict, str]:
    """Handle OAuth2 callback. Returns (osm_user_info, next_url)."""
    state_cookie = request.cookies.get("oauth_state")
    if not state_cookie:
        raise HTTPException(400, "Missing OAuth state cookie")

    try:
        payload = _serializer.loads(state_cookie, max_age=600)
    except (BadSignature, SignatureExpired):
        raise HTTPException(400, "Invalid or expired OAuth state")

    state = payload["state"]
    next_url = payload.get("next", "/")

    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    returned_state = request.query_params.get("state")
    if returned_state != state:
        raise HTTPException(400, "OAuth state mismatch")

    async with _get_oauth_client() as client:
        token = await client.fetch_token(
            OSM_TOKEN_URL,
            code=code,
            state=state,
        )
        resp = await client.get(OSM_USER_URL)
        resp.raise_for_status()
        user_data = resp.json()

    osm_user = user_data.get("user", {})
    return {
        "osm_id": osm_user["id"],
        "username": osm_user["display_name"],
    }, next_url


def create_session_cookie(user_id: int) -> str:
    """Create a signed session token for the given user ID."""
    return _serializer.dumps({"user_id": user_id})


def decode_session_cookie(token: str) -> int | None:
    """Decode session cookie. Returns user_id or None."""
    try:
        payload = _serializer.loads(token, max_age=86400 * 30)
        return payload["user_id"]
    except (BadSignature, SignatureExpired, KeyError):
        return None


def get_current_user_id(request: Request) -> int | None:
    """Extract user_id from session cookie, or None."""
    token = request.cookies.get("session")
    if not token:
        return None
    return decode_session_cookie(token)


def require_auth(request: Request) -> int:
    """Like get_current_user_id but raises 401 if not authenticated."""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(401, "Authentication required")
    return user_id

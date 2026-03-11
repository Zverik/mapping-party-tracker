"""GeoJSON validation and geometry utilities."""
import json
import hashlib
from typing import Any


class GeoJSONError(ValueError):
    pass


def _round_coords(coords: Any, precision: int = 7) -> Any:
    """Recursively round coordinates for geometry comparison."""
    if isinstance(coords, list):
        return [_round_coords(c, precision) for c in coords]
    return round(float(coords), precision)


def geometry_fingerprint(geometry: dict) -> str:
    """Return a stable hash of a geometry for equality comparison."""
    normalized = {
        "type": geometry["type"],
        "coordinates": _round_coords(geometry["coordinates"]),
    }
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def validate_and_extract_features(raw: str | bytes) -> list[dict]:
    """
    Parse GeoJSON text and return a list of individual GeoJSON Feature dicts.
    Each feature has geometry of type Polygon or MultiPolygon.
    Raises GeoJSONError on invalid input.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise GeoJSONError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise GeoJSONError("GeoJSON must be a JSON object")

    top_type = data.get("type")

    features: list[dict] = []

    if top_type == "FeatureCollection":
        raw_features = data.get("features", [])
        if not isinstance(raw_features, list):
            raise GeoJSONError("FeatureCollection.features must be an array")
        for i, f in enumerate(raw_features):
            features.extend(_extract_from_item(f, f"features[{i}]"))

    elif top_type == "Feature":
        features.extend(_extract_from_item(data, "root"))

    elif top_type in ("Polygon", "MultiPolygon"):
        features.append({
            "type": "Feature",
            "geometry": data,
            "properties": {},
        })

    else:
        raise GeoJSONError(
            f"Unsupported GeoJSON type '{top_type}'. "
            "Expected FeatureCollection, Feature, Polygon, or MultiPolygon."
        )

    if not features:
        raise GeoJSONError("No valid Polygon or MultiPolygon features found")

    return features


def _extract_from_item(item: Any, path: str) -> list[dict]:
    """Extract polygon feature(s) from a single GeoJSON item."""
    if not isinstance(item, dict):
        raise GeoJSONError(f"{path}: expected object")

    item_type = item.get("type")

    if item_type == "Feature":
        geometry = item.get("geometry")
        if not geometry:
            return []  # skip null geometries
        geo_type = geometry.get("type")
        if geo_type == "GeometryCollection":
            # Flatten geometry collection
            result = []
            for g in geometry.get("geometries", []):
                if g.get("type") in ("Polygon", "MultiPolygon"):
                    result.append({
                        "type": "Feature",
                        "geometry": g,
                        "properties": item.get("properties") or {},
                    })
            return result
        if geo_type not in ("Polygon", "MultiPolygon"):
            return []  # skip non-polygon geometries silently
        return [{
            "type": "Feature",
            "geometry": geometry,
            "properties": item.get("properties") or {},
        }]

    elif item_type in ("Polygon", "MultiPolygon"):
        return [{
            "type": "Feature",
            "geometry": item,
            "properties": {},
        }]

    return []


def feature_to_db_text(feature: dict) -> str:
    """Serialize a GeoJSON Feature to a compact JSON string for DB storage."""
    return json.dumps(feature, separators=(",", ":"))


def diff_geojson_upload(
    existing: list[dict],  # [{"id": int, "geojson": str, "status": int}]
    new_features: list[dict],  # validated Feature dicts
) -> dict:
    """
    Compute diff between existing DB polygons and new upload.

    Returns:
        {
            "keep": [(existing_id, feature_dict)],   # unchanged
            "update": [(existing_id, feature_dict)], # geometry changed
            "add": [feature_dict],                   # new
            "remove": [existing_id],                 # deleted
            "warnings": [str],                       # non-zero status affected
        }
    """
    # Build fingerprint -> existing polygon map
    existing_by_fp: dict[str, dict] = {}
    for row in existing:
        try:
            feature = json.loads(row["geojson"])
            fp = geometry_fingerprint(feature["geometry"])
            existing_by_fp[fp] = row
        except Exception:
            pass

    new_by_fp: dict[str, dict] = {}
    for feature in new_features:
        fp = geometry_fingerprint(feature["geometry"])
        new_by_fp[fp] = feature

    existing_fps = set(existing_by_fp.keys())
    new_fps = set(new_by_fp.keys())

    unchanged_fps = existing_fps & new_fps
    removed_fps = existing_fps - new_fps
    added_fps = new_fps - existing_fps

    keep = [(existing_by_fp[fp]["id"], new_by_fp[fp]) for fp in unchanged_fps]
    remove = [existing_by_fp[fp]["id"] for fp in removed_fps]
    add = [new_by_fp[fp] for fp in added_fps]

    warnings = []
    for poly_id in remove:
        row = next(r for r in existing if r["id"] == poly_id)
        if row["status"] != 0:
            warnings.append(
                f"Polygon #{poly_id} has score {row['status']} and will be removed"
            )

    return {
        "keep": keep,
        "update": [],
        "add": add,
        "remove": remove,
        "warnings": warnings,
    }

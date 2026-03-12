"""Database connection and schema management."""
import os
import logging
from contextlib import contextmanager
import mysql.connector
from mysql.connector import pooling

logger = logging.getLogger(__name__)

_pool: pooling.MySQLConnectionPool | None = None


def init_pool():
    """Initialize the MySQL connection pool."""
    global _pool
    _pool = pooling.MySQLConnectionPool(
        pool_name="mapping_party",
        pool_size=10,
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        autocommit=False,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        use_unicode=True,
    )
    logger.info("Database connection pool initialized")


@contextmanager
def get_db():
    """Context manager yielding a database connection from the pool."""
    conn = _pool.get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """Create tables if they do not exist."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                osm_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                owner_id INT NOT NULL,
                locked BOOLEAN NOT NULL DEFAULT FALSE,
                link_url TEXT,
                link_text VARCHAR(255),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS polygons (
                id INT AUTO_INCREMENT PRIMARY KEY,
                project_id INT NOT NULL,
                geojson TEXT NOT NULL,
                status INT NOT NULL DEFAULT 0,
                INDEX idx_project (project_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INT AUTO_INCREMENT PRIMARY KEY,
                polygon_id INT NOT NULL,
                user_id INT NOT NULL,
                claimed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                released_at DATETIME NULL,
                FOREIGN KEY (polygon_id) REFERENCES polygons(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cursor.close()
    logger.info("Database schema initialized")


# ─── User helpers ─────────────────────────────────────────────────────────────

def upsert_user(osm_id: int, username: str) -> dict:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "INSERT INTO users (osm_id, username) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE username = VALUES(username)",
            (osm_id, username),
        )
        cursor.execute("SELECT * FROM users WHERE osm_id = %s", (osm_id,))
        user = cursor.fetchone()
        cursor.close()
    return user


def get_user_by_id(user_id: int) -> dict | None:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
    return user


# ─── Project helpers ───────────────────────────────────────────────────────────

def list_projects() -> list[dict]:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id, p.title, p.owner_id, p.locked, p.link_url, p.link_text, p.created_at,
                   COUNT(DISTINCT poly.id) AS total_polygons,
                   COUNT(DISTINCT c.polygon_id) AS claimed_polygons
            FROM projects p
            LEFT JOIN polygons poly ON poly.project_id = p.id
            LEFT JOIN claims c ON c.polygon_id = poly.id AND c.released_at IS NULL
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
    return rows


def get_project(project_id: int) -> dict | None:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        row = cursor.fetchone()
        cursor.close()
    return row


def create_project(title: str, owner_id: int) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO projects (title, owner_id) VALUES (%s, %s)",
            (title, owner_id),
        )
        project_id = cursor.lastrowid
        cursor.close()
    return project_id


def update_project(project_id: int, title: str, link_url: str | None,
                   link_text: str | None, locked: bool):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET title=%s, link_url=%s, link_text=%s, locked=%s WHERE id=%s",
            (title, link_url, link_text, locked, project_id),
        )
        cursor.close()


# ─── Polygon helpers ───────────────────────────────────────────────────────────

def insert_polygon(project_id: int, geojson_text: str) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO polygons (project_id, geojson, status) VALUES (%s, %s, 0)",
            (project_id, geojson_text),
        )
        poly_id = cursor.lastrowid
        cursor.close()
    return poly_id


def get_polygons_for_project(project_id: int) -> list[dict]:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT poly.id, poly.project_id, poly.geojson, poly.status,
                   c.user_id AS claimed_by_id, u.username AS claimed_by_username
            FROM polygons poly
            LEFT JOIN claims c ON c.polygon_id = poly.id AND c.released_at IS NULL
            LEFT JOIN users u ON u.id = c.user_id
            WHERE poly.project_id = %s
        """, (project_id,))
        rows = cursor.fetchall()
        cursor.close()
    return rows


def get_polygon(polygon_id: int) -> dict | None:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT poly.id, poly.project_id, poly.geojson, poly.status,
                   c.user_id AS claimed_by_id, u.username AS claimed_by_username
            FROM polygons poly
            LEFT JOIN claims c ON c.polygon_id = poly.id AND c.released_at IS NULL
            LEFT JOIN users u ON u.id = c.user_id
            WHERE poly.id = %s
        """, (polygon_id,))
        row = cursor.fetchone()
        cursor.close()
    return row


def get_user_active_claim(user_id: int, project_id: int) -> dict | None:
    """Return the polygon currently claimed by user in this project, if any."""
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.id AS claim_id, c.polygon_id, c.claimed_at
            FROM claims c
            JOIN polygons poly ON poly.id = c.polygon_id
            WHERE c.user_id = %s AND poly.project_id = %s AND c.released_at IS NULL
        """, (user_id, project_id))
        row = cursor.fetchone()
        cursor.close()
    return row


def claim_polygon(polygon_id: int, user_id: int) -> bool:
    """Claim a polygon. Returns True on success, False if already claimed."""
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        # Check if already claimed
        cursor.execute(
            "SELECT id FROM claims WHERE polygon_id = %s AND released_at IS NULL",
            (polygon_id,),
        )
        if cursor.fetchone():
            cursor.close()
            return False
        cursor.execute(
            "INSERT INTO claims (polygon_id, user_id) VALUES (%s, %s)",
            (polygon_id, user_id),
        )
        cursor.close()
    return True


def release_polygon(polygon_id: int, user_id: int) -> bool:
    """Release a polygon claim. Returns True on success."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE claims SET released_at = NOW() "
            "WHERE polygon_id = %s AND user_id = %s AND released_at IS NULL",
            (polygon_id, user_id),
        )
        affected = cursor.rowcount
        cursor.close()
    return affected > 0


def set_polygon_status(polygon_id: int, user_id: int, status: int) -> bool:
    """Set polygon status. Only the current claimant can score."""
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM claims WHERE polygon_id = %s AND user_id = %s AND released_at IS NULL",
            (polygon_id, user_id),
        )
        if not cursor.fetchone():
            cursor.close()
            return False
        cursor.execute(
            "UPDATE polygons SET status = %s WHERE id = %s",
            (status, polygon_id),
        )
        cursor.close()
    return True


def get_project_stats(project_id: int) -> dict:
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN c.polygon_id IS NOT NULL THEN 1 ELSE 0 END) AS claimed
            FROM polygons poly
            LEFT JOIN claims c ON c.polygon_id = poly.id AND c.released_at IS NULL
            WHERE poly.project_id = %s
        """, (project_id,))
        counts = cursor.fetchone()

        cursor.execute("""
            SELECT status, COUNT(*) AS cnt
            FROM polygons
            WHERE project_id = %s
            GROUP BY status
        """, (project_id,))
        hist_rows = cursor.fetchall()
        cursor.close()

    histogram = {str(i): 0 for i in range(6)}
    for row in hist_rows:
        histogram[str(row["status"])] = int(row["cnt"])

    return {
        "total": int(counts["total"]) or 0,
        "claimed": int(counts["claimed"]) or 0,
        "histogram": histogram,
    }


# ─── GeoJSON update helpers ────────────────────────────────────────────────────

def get_all_polygons_raw(project_id: int) -> list[dict]:
    """Return id, geojson, status for all polygons in a project."""
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, geojson, status FROM polygons WHERE project_id = %s",
            (project_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
    return rows


def update_polygon_geojson(polygon_id: int, geojson_text: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE polygons SET geojson = %s WHERE id = %s",
            (geojson_text, polygon_id),
        )
        cursor.close()


def delete_polygon(polygon_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM polygons WHERE id = %s", (polygon_id,))
        cursor.close()

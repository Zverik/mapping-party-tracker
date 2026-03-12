# Mapping Party Tracker

A real-time collaborative web application for claiming, scoring, and releasing map polygons during mapping events and data validation sessions.

---

## Features

- **OpenStreetMap OAuth2 login** — secure, no passwords
- **GeoJSON ingestion** — upload Polygon/MultiPolygon feature collections
- **Polygon claiming** — one active claim per user per project
- **0–5 scoring system** — color-coded polygon fill
- **Live WebSocket updates** — all connected clients see changes instantly
- **Project editing** — owner can update settings and upload revised GeoJSON
- **Mobile-friendly** — works on phones and tablets

---

## Architecture

```
mapping-party-tracker/
├── main.py              # FastAPI app, all routes and WebSocket
├── database.py          # MySQL connection pool, all queries
├── auth.py              # OSM OAuth2 + signed session cookies
├── geojson_utils.py     # GeoJSON validation and diff logic
├── ws_manager.py        # WebSocket broadcast manager
├── pyproject.toml       # uv/pip dependencies
├── .env.example         # example environment variables
├── templates/
│   ├── index.html       # Homepage — project list
│   ├── map.html         # Leaflet map page
│   └── edit.html        # Project settings + polygon upload
└── static/
    ├── css/
    │   ├── main.css     # Global styles
    │   └── map.css      # Map page styles
    └── js/
        ├── main.js      # Shared utilities + homepage logic
        ├── map.js       # Leaflet map, claims, WebSocket
        └── edit.js      # Project editing logic
```

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- MySQL 8.0+ (or MariaDB 10.6+)
- An OpenStreetMap account (for OAuth credentials)

---

## Setup

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone / download the project

```bash
git clone <repo>
cd mapping-party-tracker
```

### 3. Create the database

Log in to MySQL and create the database:

```sql
CREATE DATABASE mapping_party CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'mpt'@'localhost' IDENTIFIED BY 'yourpassword';
GRANT ALL PRIVILEGES ON mapping_party.* TO 'mpt'@'localhost';
FLUSH PRIVILEGES;
```

The application will **automatically create all tables** on first startup.

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
DB_HOST=localhost
DB_USER=mpt
DB_PASSWORD=yourpassword
DB_NAME=mapping_party

OSM_CLIENT_ID=your_client_id
OSM_CLIENT_SECRET=your_client_secret

SESSION_SECRET=generate_with_python_secrets_token_hex_32

BASE_URL=http://localhost:8000
```

Generate a session secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## OSM OAuth2 Configuration

1. Go to [https://www.openstreetmap.org/oauth2/applications](https://www.openstreetmap.org/oauth2/applications)
2. Click **Register new application**
3. Fill in:
   - **Name**: Mapping Party Tracker (or anything you like)
   - **Redirect URI**: `http://localhost:8000/auth/callback` (or your `BASE_URL` + `/auth/callback`)
   - **Scopes**: `read_prefs`
4. Copy the **Client ID** and **Client Secret** into your `.env`

---

## Running

```bash
uv pip install -e .
uv run mapping-party-tracker
```

The application will:
1. Install dependencies automatically (via `pyproject.toml`)
2. Connect to MySQL
3. Create database tables if they don't exist
4. Start on `http://localhost:8000`

For auto-reload during development:

```bash
DEBUG=true uv run main.py
```

---

## Usage

### Creating a project

1. Log in with your OSM account
2. Click **New Project** on the homepage
3. Enter a title and upload a GeoJSON file containing Polygon or MultiPolygon features
4. The project appears in the list immediately

### Using the map

- **Click any polygon** to open its popup
- **Claim** an unclaimed polygon to start working on it
- **Score 0–5** using the score buttons while you have it claimed
- **Release** when you're done so others can see it's finished
- Only **one polygon can be claimed at a time** per user per project

### Editing a project

- Only the project owner can access the edit page
- Click **⚙ Edit Project** in the sidebar
- Change title, link, or lock/unlock the project
- Upload a revised GeoJSON — polygons with identical geometry **keep their scores**

---

## Polygon Status Colors

| Score | Color        | Meaning      |
|-------|-------------|--------------|
| 0     | Transparent | Not scored   |
| 1     | Red         | Poor         |
| 2     | Orange      | Fair         |
| 3     | Yellow      | Good         |
| 4     | Light green | Very good    |
| 5     | Green       | Excellent    |

## Outline Colors

| Style           | Meaning               |
|----------------|----------------------|
| Thin black      | Unclaimed             |
| Thick blue      | Claimed by other user |
| Thick red       | Claimed by you        |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/me` | Current session user |
| GET | `/api/projects` | List all projects |
| POST | `/api/projects` | Create project (multipart: title, geojson_file) |
| GET | `/api/projects/{id}` | Get project details |
| PUT | `/api/projects/{id}` | Update project settings (owner only) |
| POST | `/api/projects/{id}/upload` | Replace polygons (owner only) |
| GET | `/api/projects/{id}/polygons` | All polygons with claim info |
| GET | `/api/projects/{id}/stats` | Statistics + score histogram |
| POST | `/api/polygons/{id}/claim` | Claim a polygon |
| POST | `/api/polygons/{id}/release` | Release a polygon |
| POST | `/api/polygons/{id}/status` | Set polygon score (0–5) |
| WS | `/ws/projects/{id}` | Live update stream |

---

## WebSocket Events

Events broadcast to all clients in a project room:

```json
{"type": "claimed",  "polygon_id": 42, "user_id": 7, "username": "alice"}
{"type": "released", "polygon_id": 42}
{"type": "status",   "polygon_id": 42, "status": 3}
```

---

## Security

- Sessions use **itsdangerous** signed cookies (tamper-proof, 30-day expiry)
- OAuth state stored in a short-lived signed cookie (10-minute expiry)
- All state-changing API requests verified with **Origin header CSRF check**
- All SQL queries use **parameterized statements** (no string interpolation)
- Claim/score business rules enforced **server-side only**
- No secrets hardcoded anywhere

---

## Production Notes

- Set `BASE_URL` to your production HTTPS URL
- Session cookies automatically become `Secure` when `BASE_URL` starts with `https://`
- Put behind a reverse proxy (nginx/Caddy) for TLS termination
- Set `DEBUG=false` (default) in production
- Consider increasing the MySQL connection pool size for high-traffic deployments

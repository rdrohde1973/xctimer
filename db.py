"""SQLite connection, schema, migrations, and seed for XCTimer.

One box, one waitress process, one SQLite file in WAL mode — see handoff §6.5.
Every connection MUST apply the WAL pragmas below (prevents "database is locked"
under concurrent meet-day recording).
"""
import os
import sqlite3

DB_PATH = os.environ.get("XCTIMER_DB", os.path.join(os.path.dirname(__file__), "xctimer.db"))


def connect():
    """Open a connection with the required pragmas (handoff §6.5)."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # concurrent readers + one writer
    cur.execute("PRAGMA synchronous=NORMAL")    # safe under WAL, much faster than FULL
    cur.execute("PRAGMA busy_timeout=5000")     # wait up to 5s for the lock
    cur.execute("PRAGMA foreign_keys=ON")
    return conn


# --- Schema (handoff §5). district_id lives on top-level rows; children inherit. ---
SCHEMA = """
CREATE TABLE IF NOT EXISTS districts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    logo_path TEXT,
    settings_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    name TEXT NOT NULL,
    bib_start INTEGER,
    bib_end INTEGER,
    logo_path TEXT,
    sheet_url TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    district_id INTEGER REFERENCES districts(id),   -- NULL allowed for super_admin
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    role TEXT NOT NULL,                              -- super_admin|district_admin|coach|timer
    password_hash TEXT,
    setup_token TEXT,
    token_expires TEXT,
    last_login TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_schools (
    user_id INTEGER NOT NULL REFERENCES users(id),
    school_id INTEGER NOT NULL REFERENCES schools(id),
    PRIMARY KEY (user_id, school_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    expires TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS athletes (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    bib INTEGER,
    name TEXT NOT NULL,
    grade INTEGER,
    gender TEXT,
    epc TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meets (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    sport TEXT NOT NULL,                             -- 'xc' | 'track'
    name TEXT NOT NULL,
    date TEXT,
    host_school_id INTEGER REFERENCES schools(id),
    public_token TEXT,                               -- unauthenticated results page
    timer_token TEXT,                                -- meet-day no-login QR (handoff §11)
    timer_token_expires TEXT,                        -- auto-expire at end of meet day
    settings_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meet_schools (
    meet_id INTEGER NOT NULL REFERENCES meets(id),
    school_id INTEGER NOT NULL REFERENCES schools(id),
    PRIMARY KEY (meet_id, school_id)
);

-- XC engine
CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY,
    meet_id INTEGER NOT NULL REFERENCES meets(id),
    name TEXT,
    capture_mode TEXT,
    start_time TEXT,
    stop_time TEXT,
    public_token TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS finishers (
    id INTEGER PRIMARY KEY,
    race_id INTEGER NOT NULL REFERENCES races(id),
    seq INTEGER,
    bib INTEGER,
    finish_time TEXT,
    elapsed_seconds REAL,
    dq INTEGER DEFAULT 0,
    snap_name TEXT,
    snap_grade INTEGER,
    snap_gender TEXT,
    snap_school TEXT,
    archived_at TEXT
);

-- Track engine
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT,                                       -- track|field|relay
    unit TEXT,                                       -- seconds|metric
    sort INTEGER,
    laned INTEGER DEFAULT 0,
    scoring_order TEXT                               -- 'asc' (time) | 'desc' (distance/height)
);

CREATE TABLE IF NOT EXISTS points_tables (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    point_values_json TEXT
);

CREATE TABLE IF NOT EXISTS meet_events (
    id INTEGER PRIMARY KEY,
    meet_id INTEGER NOT NULL REFERENCES meets(id),
    event_id INTEGER NOT NULL REFERENCES events(id),
    gender TEXT,
    grade INTEGER,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    meet_event_id INTEGER NOT NULL REFERENCES meet_events(id),
    runner_id INTEGER REFERENCES athletes(id),
    school_id INTEGER REFERENCES schools(id),
    relay_label TEXT,
    members_json TEXT,
    seed REAL,
    heat INTEGER,
    lane INTEGER
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    mark_seconds REAL,
    mark_metric REAL,
    attempts_json TEXT,
    place INTEGER,
    dq INTEGER DEFAULT 0,
    snap_name TEXT,
    snap_bib INTEGER,
    snap_school TEXT
);
"""

# Index the scoping/join columns (handoff §6.5) — every query filters by these.
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_schools_district ON schools(district_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_district ON users(district_id)",
    "CREATE INDEX IF NOT EXISTS idx_athletes_school ON athletes(school_id)",
    "CREATE INDEX IF NOT EXISTS idx_athletes_bib ON athletes(bib)",
    "CREATE INDEX IF NOT EXISTS idx_meets_district ON meets(district_id)",
    "CREATE INDEX IF NOT EXISTS idx_races_meet ON races(meet_id)",
    "CREATE INDEX IF NOT EXISTS idx_finishers_race ON finishers(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_finishers_bib ON finishers(bib)",
    "CREATE INDEX IF NOT EXISTS idx_meet_events_meet ON meet_events(meet_id)",
    "CREATE INDEX IF NOT EXISTS idx_entries_meet_event ON entries(meet_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_results_entry ON results(entry_id)",
]

# Global built-in events catalog (handoff §4/§11: global defaults, district-overridable later).
# 11-event catalog mirroring the Track reference app. name, kind, unit, sort, laned, scoring_order.
SEED_EVENTS = [
    ("100m",          "track", "seconds", 10, 1, "asc"),
    ("200m",          "track", "seconds", 20, 1, "asc"),
    ("400m",          "track", "seconds", 30, 1, "asc"),
    ("800m",          "track", "seconds", 40, 0, "asc"),
    ("1600m",         "track", "seconds", 50, 0, "asc"),
    ("3200m",         "track", "seconds", 60, 0, "asc"),
    ("4x100m Relay",  "relay", "seconds", 70, 1, "asc"),
    ("4x400m Relay",  "relay", "seconds", 80, 1, "asc"),
    ("Long Jump",     "field", "metric",  90, 0, "desc"),
    ("High Jump",     "field", "metric", 100, 0, "desc"),
    ("Shot Put",      "field", "metric", 110, 0, "desc"),
]

# Default points tables. NOTE: reconcile exact values against track_timer.py's
# points_tables seed in Phase 4 before scoring goes live.
SEED_POINTS_TABLES = [
    ("Individual (1-8)", "[10, 8, 6, 5, 4, 3, 2, 1]"),
    ("Relay (1-8)",      "[20, 16, 12, 10, 8, 6, 4, 2]"),
]


def _column_names(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(conn):
    """Additive, idempotent column migrations (SQLite can only ADD COLUMN)."""
    # Sessions carry a kind + meet_id so the same table holds both normal user
    # logins and the meet-day no-login QR sessions (handoff §11).
    scols = _column_names(conn, "sessions")
    if "kind" not in scols:
        conn.execute("ALTER TABLE sessions ADD COLUMN kind TEXT DEFAULT 'user'")
    if "meet_id" not in scols:
        conn.execute("ALTER TABLE sessions ADD COLUMN meet_id INTEGER")


def init_db():
    """Create schema + indexes and seed the global catalog if empty. Idempotent."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        for stmt in INDEXES:
            conn.execute(stmt)
        if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO events (name, kind, unit, sort, laned, scoring_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                SEED_EVENTS,
            )
        if conn.execute("SELECT COUNT(*) FROM points_tables").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO points_tables (name, point_values_json) VALUES (?, ?)",
                SEED_POINTS_TABLES,
            )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"XCTimer DB initialized at {DB_PATH}")

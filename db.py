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
    does_xc INTEGER DEFAULT 1,
    does_track INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1,
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

-- District record board (imported; shown in AI Insights)
CREATE TABLE IF NOT EXISTS district_records (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    gender TEXT,
    grade TEXT,
    event TEXT,
    mark TEXT,
    athlete TEXT,
    school TEXT,
    year TEXT
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

-- District-level waiver templates a district admin writes once and reuses.
CREATE TABLE IF NOT EXISTS waiver_templates (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- One row per waiver sent to an athlete's parent. The doc text is snapshotted so
-- the signed record is exactly what was agreed to, even if the template changes.
CREATE TABLE IF NOT EXISTS athlete_waivers (
    id INTEGER PRIMARY KEY,
    athlete_id INTEGER NOT NULL REFERENCES athletes(id),
    template_id INTEGER REFERENCES waiver_templates(id),
    token TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',      -- pending | signed | void
    doc_title TEXT,
    doc_body TEXT,
    doc_hash TEXT,
    sent_to TEXT,
    signer_name TEXT,
    signer_relationship TEXT,
    signer_sig_path TEXT,
    signed_at TEXT,
    signed_ip TEXT,
    signed_ua TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
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
    "CREATE INDEX IF NOT EXISTS idx_records_district ON district_records(district_id)",
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

# Points tables (from the Track reference app). Relays score the same table
# times relay_multiplier (default 1.0). Meets pick one via meets.points_table_id.
SEED_POINTS_TABLES = [
    ("Dual 5-3-1",                    "[5, 3, 1]"),
    ("Dual 5-3-2-1",                  "[5, 3, 2, 1]"),
    ("Invitational 10-8-6-4-2-1",     "[10, 8, 6, 4, 2, 1]"),
    ("Invitational 10-8-6-5-4-3-2-1", "[10, 8, 6, 5, 4, 3, 2, 1]"),
]
DEFAULT_POINTS_TABLE = "Invitational 10-8-6-4-2-1"


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
    # Demo accounts: read-only + anonymized names (handoff §8 demo mode).
    if "is_demo" not in _column_names(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN is_demo INTEGER DEFAULT 0")

    # Roster: per-athlete sport membership (XC / Track) + active flag. One shared
    # athlete list; grade bumps preserve historical results (stored per-result).
    acols = _column_names(conn, "athletes")
    if "does_xc" not in acols:
        conn.execute("ALTER TABLE athletes ADD COLUMN does_xc INTEGER DEFAULT 1")
    if "does_track" not in acols:
        conn.execute("ALTER TABLE athletes ADD COLUMN does_track INTEGER DEFAULT 1")
    if "active" not in acols:      # graduated athletes go inactive, never deleted
        conn.execute("ALTER TABLE athletes ADD COLUMN active INTEGER DEFAULT 1")
    # Contact / parent / emergency / physical fields (importable from the roster file).
    for col in ("email", "phone", "parent_name", "parent_email", "parent_phone",
                "emergency_name", "emergency_phone", "physical_date", "dob"):
        if col not in acols:
            conn.execute(f"ALTER TABLE athletes ADD COLUMN {col} TEXT")

    # Waiver signing can also capture family physician + health insurance.
    wcols = _column_names(conn, "athlete_waivers")
    for col in ("physician_name", "physician_phone", "insurance_provider", "insurance_policy"):
        if col not in wcols:
            conn.execute(f"ALTER TABLE athlete_waivers ADD COLUMN {col} TEXT")

    # Meet setup fields ported from the reference apps.
    mcols = _column_names(conn, "meets")
    if "event_limit" not in mcols:      # track: max individual+field events/athlete
        conn.execute("ALTER TABLE meets ADD COLUMN event_limit INTEGER DEFAULT 4")
    if "lanes" not in mcols:            # track: lanes for sprint heat/lane draws
        conn.execute("ALTER TABLE meets ADD COLUMN lanes INTEGER DEFAULT 8")
    if "points_table_id" not in mcols:  # track: selected scoring table
        conn.execute("ALTER TABLE meets ADD COLUMN points_table_id INTEGER")
    if "team_scoring" not in mcols:     # xc: team-score tab on/off
        conn.execute("ALTER TABLE meets ADD COLUMN team_scoring INTEGER DEFAULT 1")

    mecols = _column_names(conn, "meet_events")
    if "combine_id" not in mecols:
        conn.execute("ALTER TABLE meet_events ADD COLUMN combine_id INTEGER")
    if "bar_heights" not in mecols:      # High Jump: JSON list of bar heights (ft-in)
        conn.execute("ALTER TABLE meet_events ADD COLUMN bar_heights TEXT")

    ptcols = _column_names(conn, "points_tables")
    if "relay_multiplier" not in ptcols:
        conn.execute("ALTER TABLE points_tables ADD COLUMN relay_multiplier REAL DEFAULT 1.0")
    if "builtin" not in ptcols:
        conn.execute("ALTER TABLE points_tables ADD COLUMN builtin INTEGER DEFAULT 1")

    # Prevent duplicate event×gender×grade rows (enables INSERT OR IGNORE batch add).
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_meet_events_combo "
                 "ON meet_events(meet_id, event_id, gender, grade)")

    # Server-backed track tap timer so a distance/relay heat can be timed on one
    # device and assigned on another (multi-device, like the XC race console).
    # One clock row per (meet_event, heat); taps carry an elapsed time + optional
    # assigned entry. heat 0 == "all entries" (no heat filter).
    conn.execute("""CREATE TABLE IF NOT EXISTS track_clocks (
        meet_event_id INTEGER NOT NULL,
        heat INTEGER NOT NULL DEFAULT 0,
        start_time TEXT,
        stop_time TEXT,
        PRIMARY KEY (meet_event_id, heat))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS track_taps (
        id INTEGER PRIMARY KEY,
        meet_event_id INTEGER NOT NULL,
        heat INTEGER NOT NULL DEFAULT 0,
        seq INTEGER,
        elapsed_seconds REAL,
        entry_id INTEGER,
        created_at TEXT DEFAULT (datetime('now')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_track_taps ON track_taps(meet_event_id, heat)")

    # Ensure the named points tables exist (older DBs seeded a different set).
    for name, vals in SEED_POINTS_TABLES:
        if not conn.execute("SELECT 1 FROM points_tables WHERE name=?", (name,)).fetchone():
            conn.execute("INSERT INTO points_tables (name, point_values_json) VALUES (?,?)",
                         (name, vals))


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

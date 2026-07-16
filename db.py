"""SQLite connection, schema, migrations, and seed for XCTimer.

One box, one waitress process, one SQLite file in WAL mode — see handoff §6.5.
Every connection MUST apply the WAL pragmas below (prevents "database is locked"
under concurrent meet-day recording).
"""
import os
import sqlite3

DB_PATH = os.environ.get("XCTIMER_DB", os.path.join(os.path.dirname(__file__), "xctimer.db"))


def connect():
    """Open a connection. Only cheap, lock-free per-connection pragmas here — WAL mode
    is a PERSISTENT db-level property set once in init_db(); running `PRAGMA journal_mode=WAL`
    on every connect needs a write lock and, under load, throws 'database is locked' even
    on read connections (that regressed the whole app). See init_db()."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA busy_timeout=10000")    # wait up to 10s for the lock
    cur.execute("PRAGMA synchronous=NORMAL")    # safe under WAL, much faster than FULL
    cur.execute("PRAGMA foreign_keys=ON")
    # SAFETY NET (2026-07-14 outage): register every connection opened during a request
    # so the app's teardown hook closes any that a route leaked (e.g. by raising between
    # a write and conn.close()). A single leaked write-locked connection once cascaded
    # into site-wide "database is locked" 500s. Closing twice is a harmless no-op;
    # closing an unleaked-but-uncommitted conn rolls back and RELEASES THE LOCK.
    try:
        from flask import g, has_app_context
        if has_app_context():
            if not hasattr(g, "_db_conns"):
                g._db_conns = []
            g._db_conns.append(conn)
    except Exception:  # noqa: BLE001 — scripts/CLI run without flask context
        pass
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
    district_id INTEGER REFERENCES districts(id),    -- NULL for community road events
    organizer_id INTEGER REFERENCES organizers(id),  -- set for community road events
    sport TEXT NOT NULL,                             -- 'xc' | 'track' | 'road'
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

-- Community road-race organizers (a tenant distinct from school districts).
-- A road EVENT is a meets row with organizer_id set (district_id NULL).
CREATE TABLE IF NOT EXISTS organizers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    logo_path TEXT,
    settings_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Individual registrants for a community road event. No school, no PII —
-- just what a race result needs. Born into one distance (race_id).
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    meet_id INTEGER NOT NULL REFERENCES meets(id),
    race_id INTEGER REFERENCES races(id),
    bib INTEGER,
    name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    city TEXT,
    club TEXT,
    paid INTEGER DEFAULT 1,          -- payment groundwork: 1=paid/free, 0=owes fee
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(meet_id, bib)
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

-- Road events: which athletes are assigned to which event (race). Exactly one
-- event per athlete per meet (UNIQUE on meet_id+athlete_id enforces it).
CREATE TABLE IF NOT EXISTS race_entries (
    id INTEGER PRIMARY KEY,
    meet_id INTEGER NOT NULL REFERENCES meets(id),
    race_id INTEGER NOT NULL REFERENCES races(id),
    athlete_id INTEGER NOT NULL REFERENCES athletes(id),
    UNIQUE(meet_id, athlete_id)
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
    "CREATE INDEX IF NOT EXISTS idx_race_entries_race ON race_entries(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_race_entries_meet ON race_entries(meet_id)",
    "CREATE INDEX IF NOT EXISTS idx_participants_meet ON participants(meet_id)",
    "CREATE INDEX IF NOT EXISTS idx_participants_race ON participants(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_meets_organizer ON meets(organizer_id)",
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


def _migrate_meets_organizer(conn):
    """Add meets.organizer_id and make meets.district_id nullable (SQLite needs a
    table rebuild to drop a NOT NULL). Idempotent: only rebuilds when needed."""
    info = conn.execute("PRAGMA table_info(meets)").fetchall()
    cols = {r[1]: r for r in info}          # name -> (cid,name,type,notnull,dflt,pk)
    has_org = "organizer_id" in cols
    district_notnull = bool(cols["district_id"][3]) if "district_id" in cols else False
    if has_org and not district_notnull:
        return  # already migrated

    # Rebuild meets with district_id nullable + organizer_id, preserving every row/id.
    old_cols = [r[1] for r in info]
    copy_cols = ", ".join(old_cols)
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS meets_rebuild")
        conn.execute("""
            CREATE TABLE meets_rebuild (
                id INTEGER PRIMARY KEY,
                district_id INTEGER REFERENCES districts(id),
                organizer_id INTEGER REFERENCES organizers(id),
                sport TEXT NOT NULL,
                name TEXT NOT NULL,
                date TEXT,
                host_school_id INTEGER REFERENCES schools(id),
                public_token TEXT,
                timer_token TEXT,
                timer_token_expires TEXT,
                settings_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                event_limit INTEGER DEFAULT 4,
                lanes INTEGER DEFAULT 8,
                points_table_id INTEGER,
                team_scoring INTEGER DEFAULT 1,
                public_names TEXT
            )""")
        # Insert old rows into the matching columns (organizer_id defaults to NULL).
        conn.execute(f"INSERT INTO meets_rebuild ({copy_cols}) SELECT {copy_cols} FROM meets")
        conn.execute("DROP TABLE meets")
        conn.execute("ALTER TABLE meets_rebuild RENAME TO meets")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def migrate(conn):
    """Additive, idempotent column migrations (SQLite can only ADD COLUMN)."""
    # Sessions carry a kind + meet_id so the same table holds both normal user
    # logins and the meet-day no-login QR sessions (handoff §11).
    scols = _column_names(conn, "sessions")
    if "kind" not in scols:
        conn.execute("ALTER TABLE sessions ADD COLUMN kind TEXT DEFAULT 'user'")
    if "meet_id" not in scols:
        conn.execute("ALTER TABLE sessions ADD COLUMN meet_id INTEGER")
    if "last_seen" not in scols:      # idle-timeout tracking (compliance Phase 2)
        conn.execute("ALTER TABLE sessions ADD COLUMN last_seen TEXT")
        # grandfather existing sessions: give them a fresh idle window, not an instant logout
        conn.execute("UPDATE sessions SET last_seen = "
                     "strftime('%Y-%m-%dT%H:%M:%S+00:00','now') WHERE last_seen IS NULL")
    # Demo accounts: read-only + anonymized names (handoff §8 demo mode).
    ucols = _column_names(conn, "users")
    if "is_demo" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN is_demo INTEGER DEFAULT 0")
    if "mfa_enabled" not in ucols:    # per-user MFA opt-in flag (enforcement TBD)
        conn.execute("ALTER TABLE users ADD COLUMN mfa_enabled INTEGER DEFAULT 0")
    if "organizer_id" not in ucols:   # race_director users are scoped to one organizer
        conn.execute("ALTER TABLE users ADD COLUMN organizer_id INTEGER")

    # Community road events live in `meets` owned by an organizer (no district).
    # That requires meets.district_id to be nullable + an organizer_id column —
    # relax the original NOT NULL via a one-time, idempotent table rebuild.
    _migrate_meets_organizer(conn)

    # Roster: per-athlete sport membership (XC / Track) + active flag. One shared
    # athlete list; grade bumps preserve historical results (stored per-result).
    acols = _column_names(conn, "athletes")
    if "does_xc" not in acols:
        conn.execute("ALTER TABLE athletes ADD COLUMN does_xc INTEGER DEFAULT 1")
    if "does_track" not in acols:
        conn.execute("ALTER TABLE athletes ADD COLUMN does_track INTEGER DEFAULT 1")
    if "active" not in acols:      # graduated athletes go inactive, never deleted
        conn.execute("ALTER TABLE athletes ADD COLUMN active INTEGER DEFAULT 1")
    if "age" not in acols:         # road races: division is gender x age (no grade)
        conn.execute("ALTER TABLE athletes ADD COLUMN age INTEGER")
    if "does_road" not in acols:   # road: opt-in per athlete (only shown in road-enabled districts)
        conn.execute("ALTER TABLE athletes ADD COLUMN does_road INTEGER DEFAULT 0")
    if "road_event" not in acols:  # road: roster-designated event label (e.g. "5K"), auto-assigned
        conn.execute("ALTER TABLE athletes ADD COLUMN road_event TEXT")
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
    if "public_names" not in mcols:     # public results: 'full' | 'initials' | 'bib'
        conn.execute("ALTER TABLE meets ADD COLUMN public_names TEXT")

    fcols = _column_names(conn, "finishers")
    if "snap_age" not in fcols:          # road races: snapshot age for gender×age grouping
        conn.execute("ALTER TABLE finishers ADD COLUMN snap_age INTEGER")

    rcols = _column_names(conn, "races")
    if "age_brackets" not in rcols:      # road events: per-event age-group override (JSON list)
        conn.execute("ALTER TABLE races ADD COLUMN age_brackets TEXT")

    if "participants" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        if "paid" not in _column_names(conn, "participants"):  # payment groundwork
            conn.execute("ALTER TABLE participants ADD COLUMN paid INTEGER DEFAULT 1")

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

    # Audit log (compliance Phase 3): who viewed / changed / exported / deleted records.
    # One row per auditable request (see audit.py). Retained ~13 months, pruned on the
    # Console load. Lives in this DB, so it rides along in the nightly encrypted backup.
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        actor_id INTEGER,
        actor_email TEXT,
        actor_role TEXT,
        district_id INTEGER,
        action TEXT,
        method TEXT,
        path TEXT,
        status INTEGER,
        ip TEXT,
        detail TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_district ON audit_log(district_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id)")

    # Email-code MFA (compliance): a short-lived challenge per pending sign-in, and
    # long-lived "remembered device" tokens so MFA users aren't prompted every login.
    conn.execute("""CREATE TABLE IF NOT EXISTS mfa_challenges (
        id INTEGER PRIMARY KEY,
        token TEXT UNIQUE,
        user_id INTEGER NOT NULL,
        code_hash TEXT,
        next TEXT,
        attempts INTEGER DEFAULT 0,
        expires TEXT,
        created_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mfa_devices (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        token_hash TEXT,
        expires TEXT,
        created_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mfa_dev ON mfa_devices(user_id, token_hash)")

    # Ensure the named points tables exist (older DBs seeded a different set).
    for name, vals in SEED_POINTS_TABLES:
        if not conn.execute("SELECT 1 FROM points_tables WHERE name=?", (name,)).fetchone():
            conn.execute("INSERT INTO points_tables (name, point_values_json) VALUES (?,?)",
                         (name, vals))


def init_db():
    """Create schema + indexes and seed the global catalog if empty. Idempotent."""
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")   # persistent db-level mode — set ONCE here
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

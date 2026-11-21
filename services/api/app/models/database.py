"""Transactional, versioned SQLite persistence for platform workflows."""
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
MIGRATIONS = {1: (
    """CREATE TABLE proposals (
        id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL,
        status TEXT NOT NULL, version INTEGER NOT NULL CHECK(version >= 1),
        snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
        parties_json TEXT NOT NULL CHECK(json_valid(parties_json)),
        created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE proposal_decisions (
        proposal_id TEXT NOT NULL REFERENCES proposals(id), org_id TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('approve', 'reject')),
        comment TEXT, decided_at TEXT NOT NULL, PRIMARY KEY(proposal_id, org_id)
    )""",
    """CREATE TABLE audit_events (
        id TEXT PRIMARY KEY, org_id TEXT, actor TEXT NOT NULL CHECK(actor IN ('agent', 'user')),
        event_type TEXT NOT NULL, entity TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at TEXT NOT NULL
    )""",
    """CREATE TABLE audit_visibility (
        event_id TEXT NOT NULL REFERENCES audit_events(id), org_id TEXT NOT NULL,
        PRIMARY KEY(event_id, org_id)
    )""",
), 2: (
    "CREATE UNIQUE INDEX one_active_proposal ON proposals(opportunity_id) WHERE status != 'rejected'",
    """CREATE TRIGGER immutable_proposal_snapshot BEFORE UPDATE OF snapshot_json, parties_json,
        opportunity_id, created_by, created_at ON proposals
        BEGIN SELECT RAISE(ABORT, 'proposal snapshot and parties are immutable'); END""",
    """CREATE TABLE runtime_state (
        id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL DEFAULT 0,
        last_scan_json TEXT CHECK(last_scan_json IS NULL OR json_valid(last_scan_json))
    )""",
    "INSERT INTO runtime_state(id) VALUES(1)",
    "CREATE INDEX audit_visibility_org ON audit_visibility(org_id, event_id)",
)}


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError("SQLite schema is newer than this API supports")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class Database:
    """Short-lived connections; SQLite serializes writers across threads/processes."""

    def __init__(self, path: Path):
        import threading
        self.path = Path(path)
        self._ready = False
        self._lock = threading.Lock()

    def initialize(self):
        with self._lock:
            if not self._ready:
                initialize_database(self.path)
                self._ready = True

    def transaction(self, *, write: bool = False):
        from contextlib import contextmanager

        @contextmanager
        def session():
            self.initialize()
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return session()

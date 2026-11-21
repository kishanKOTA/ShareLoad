"""Explicit organization visibility; audit writes can join workflow transactions."""
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.models.database import Database
from app.schemas import Actor, AuditEvent


class AuditLog:
    def __init__(self, database: Database):
        self.database = database

    def record(self, *, actor: Actor, event_type: str, entity: str,
               visible_to, org_id=None, payload=None, connection=None) -> AuditEvent:
        if connection is None:
            with self.database.transaction(write=True) as connection:
                return self.record(actor=actor, event_type=event_type, entity=entity,
                                   org_id=org_id, payload=payload, visible_to=visible_to,
                                   connection=connection)
        event = AuditEvent(id=f"evt-{uuid4().hex}", org_id=org_id, actor=actor,
                           event_type=event_type, entity=entity, payload=payload or {},
                           created_at=datetime.now(timezone.utc))
        connection.execute("INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)", (
            event.id, event.org_id, event.actor.value, event.event_type, event.entity,
            json.dumps(event.payload), event.created_at.isoformat(),
        ))
        connection.executemany("INSERT INTO audit_visibility VALUES (?, ?)",
                               [(event.id, org) for org in set(visible_to)])
        return event

    def list_for(self, org_id: str) -> list[AuditEvent]:
        with self.database.transaction() as connection:
            rows = connection.execute("""SELECT e.* FROM audit_events e
                JOIN audit_visibility v ON v.event_id=e.id
                WHERE v.org_id=? ORDER BY e.rowid""", (org_id,)).fetchall()
            return [AuditEvent(**{
                "id": row["id"], "org_id": row["org_id"], "actor": row["actor"],
                "event_type": row["event_type"], "entity": row["entity"],
                "payload": json.loads(row["payload_json"]), "created_at": row["created_at"],
            }) for row in rows]

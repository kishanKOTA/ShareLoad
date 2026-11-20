"""In-memory audit log (the PRD allows in-memory storage for the demo).

Each event records who acted (``org_id``) but may be visible to more orgs: a
proposal decision by one party is shown to both. Agent scan events have no
owning org and are visible to everyone.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.schemas import Actor, AuditEvent


class AuditLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[tuple[AuditEvent, frozenset[str] | None]] = []
        self._ids = itertools.count(1)

    def record(
        self,
        *,
        actor: Actor,
        event_type: str,
        entity: str,
        org_id: str | None = None,
        payload: dict[str, Any] | None = None,
        visible_to: Iterable[str] | None = None,
    ) -> AuditEvent:
        """Append an event. ``visible_to=None`` means every org can see it."""
        with self._lock:
            event = AuditEvent(
                id=f"evt-{next(self._ids)}",
                org_id=org_id,
                actor=actor,
                event_type=event_type,
                entity=entity,
                payload=payload or {},
                created_at=datetime.now(timezone.utc),
            )
            self._events.append((event, None if visible_to is None else frozenset(visible_to)))
            return event

    def list_for(self, org_id: str) -> list[AuditEvent]:
        """Events this org may see, oldest first."""
        with self._lock:
            return [e for e, seen_by in self._events if seen_by is None or org_id in seen_by]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._ids = itertools.count(1)

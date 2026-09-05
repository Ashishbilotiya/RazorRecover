"""Pydantic schemas for the audit trail.

The audit logger writes append-only rows via ORM; this module exposes a
Pydantic representation for callers that want to read the trail back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogEntry(BaseModel):
    """One audit log record returned by the API layer."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    actor: str
    decision: str | None
    reason: str | None
    event_metadata: dict[str, Any] | None = None
    recovery_case_id: str | None = None
    transaction_id: str | None = None
    webhook_event_id: str | None = None
    created_at: datetime


__all__ = ["AuditLogEntry"]

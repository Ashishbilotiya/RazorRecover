

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Transaction
from backend.schemas.transaction import TransactionSummary

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionSummary])
def list_transactions(
    status: str | None = Query(
        default=None,
        description="Optional filter: created | captured | failed | refunded | ...",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[TransactionSummary]:
    query = session.query(Transaction).order_by(Transaction.created_at.desc())
    if status is not None:
        query = query.filter(Transaction.status == status.lower())
    rows = query.offset(offset).limit(limit).all()
    return [TransactionSummary.model_validate(row) for row in rows]


__all__ = ["router"]

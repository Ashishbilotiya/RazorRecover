"""Inference wrapper — loads the persisted model and returns predictions.

Critical rule (CLAUDE.md sections 11, 21): ML predicts. Inference never
calls Razorpay, never triggers actions, never bypasses policy. The recovery
agent + policy engine consume its output.

See CLAUDE.md section 11 example output::

    {
        "recovery_probability": 0.87,
        "revenue_at_risk": 4350.0
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from backend.ml.features import FeatureSchema, FEATURE_COLUMNS

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[2] / "models" / "recovery_model.pkl"
)


@dataclass(frozen=True)
class RecoveryPrediction:
    recovery_probability: float
    revenue_at_risk: float  # INR

    def to_dict(self) -> dict[str, float]:
        return {
            "recovery_probability": float(self.recovery_probability),
            "revenue_at_risk": float(self.revenue_at_risk),
        }


class ModelNotFoundError(FileNotFoundError):
    """Raised when the persisted model artifact cannot be located."""


@lru_cache(maxsize=1)
def load_model(model_path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    """Load the persisted pipeline artifact (cached for the process lifetime)."""
    if not model_path.exists():
        raise ModelNotFoundError(
            f"No model artifact at {model_path}. "
            "Train first via `python -m backend.ml.model`."
        )
    artifact = joblib.load(model_path)
    required_keys = {"pipeline", "schema", "decision_thresholds", "model_version"}
    missing = required_keys - set(artifact.keys())
    if missing:
        raise ModelNotFoundError(
            f"Model artifact at {model_path} is missing keys: {sorted(missing)}"
        )
    return artifact


def reset_model_cache() -> None:
    """Clear the cached model — used by tests when they swap artifacts."""
    load_model.cache_clear()


def _coerce_input(transaction: dict[str, Any], schema: FeatureSchema) -> pd.DataFrame:
    """Build a single-row DataFrame that the trained pipeline can score."""
    row: dict[str, Any] = {}
    for column in schema.all:
        if column not in transaction:
            raise ValueError(
                f"Missing required feature '{column}' in transaction input"
            )
        row[column] = transaction[column]
    return pd.DataFrame([row], columns=list(FEATURE_COLUMNS))


def predict_recovery(
    transaction: dict[str, Any],
    *,
    model_path: Path = DEFAULT_MODEL_PATH,
    paise_to_rupees: float = 100.0,
) -> RecoveryPrediction:
    """Score a single transaction; return probability + revenue at risk."""
    artifact = load_model(model_path)
    pipeline = artifact["pipeline"]
    schema = artifact["schema"]

    df = _coerce_input(transaction, schema)
    proba = float(pipeline.predict_proba(df)[0, 1])
    # Clamp to [0, 1] defensively — logistic regression can't go out of bounds
    # but the contract downstream expects it.
    proba = min(max(proba, 0.0), 1.0)

    amount_rupees = float(transaction["amount"]) / paise_to_rupees
    revenue_at_risk = amount_rupees * proba

    return RecoveryPrediction(
        recovery_probability=proba,
        revenue_at_risk=revenue_at_risk,
    )


def predict_recovery_batch(
    transactions: list[dict[str, Any]],
    *,
    model_path: Path = DEFAULT_MODEL_PATH,
    paise_to_rupees: float = 100.0,
) -> list[RecoveryPrediction]:
    """Score many transactions at once."""
    if not transactions:
        return []
    artifact = load_model(model_path)
    pipeline = artifact["pipeline"]
    schema = artifact["schema"]

    df = pd.DataFrame(transactions)
    for column in schema.all:
        if column not in df.columns:
            raise ValueError(f"Missing required feature '{column}' in batch input")
    df = df[list(FEATURE_COLUMNS)]

    probas: np.ndarray = pipeline.predict_proba(df)[:, 1]
    amounts = df["amount"].to_numpy(dtype=np.float64) / paise_to_rupees
    return [
        RecoveryPrediction(
            recovery_probability=float(min(max(p, 0.0), 1.0)),
            revenue_at_risk=float(a * min(max(p, 0.0), 1.0)),
        )
        for p, a in zip(probas, amounts)
    ]


__all__ = [
    "DEFAULT_MODEL_PATH",
    "ModelNotFoundError",
    "RecoveryPrediction",
    "load_model",
    "predict_recovery",
    "predict_recovery_batch",
    "reset_model_cache",
]
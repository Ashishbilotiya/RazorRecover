"""Feature engineering for the recovery prediction model.

The pipeline here is saved alongside the model artifact so inference
loads a single ``joblib.load(...)`` and never has to rebuild transformers.

Schema is locked down in :data:`FEATURE_COLUMNS` so the dataset generator,
training, and inference all agree on the same column set. Adding/removing a
feature requires editing only this module.

See CLAUDE.md section 12.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC_FEATURES: tuple[str, ...] = (
    "amount",
    "customer_transaction_count",
    "customer_success_rate",
    "customer_failure_rate",
    "customer_total_spend",
    "average_order_value",
    "previous_retry_count",
    "time_since_last_success",
    "hour_of_day",
    "day_of_week",
    "merchant_success_rate",
    "payment_method_success_rate",
    "recent_failure_rate",
)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "payment_method",
    "failure_reason",
)

# Columns that are never inputs (id, label, leakage-prone artifacts).
NON_FEATURE_COLUMNS: frozenset[str] = frozenset(
    {"transaction_id", "customer_id", "recoverable", "recovery_probability"}
)

FEATURE_COLUMNS: tuple[str, ...] = NUMERIC_FEATURES + CATEGORICAL_FEATURES


@dataclass(frozen=True)
class FeatureSchema:
    """Single source of truth for the feature layout."""

    numeric: tuple[str, ...] = NUMERIC_FEATURES
    categorical: tuple[str, ...] = CATEGORICAL_FEATURES
    non_feature: frozenset[str] = NON_FEATURE_COLUMNS

    @property
    def all(self) -> tuple[str, ...]:
        return self.numeric + self.categorical


def build_preprocessor(schema: FeatureSchema | None = None) -> ColumnTransformer:
    """Compose the column transformer used inside the training pipeline."""
    schema = schema or FeatureSchema()
    numeric_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipeline, list(schema.numeric)),
            ("cat", categorical_pipeline, list(schema.categorical)),
        ]
    )


def split_features_target(
    df,
    schema: FeatureSchema | None = None,
    target_column: str = "recoverable",
):
    """Drop non-feature columns and return ``(X, y)``."""
    schema = schema or FeatureSchema()
    feature_cols: Sequence[str] = schema.all
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required feature columns: {missing}")
    X = df[list(feature_cols)].copy()
    if target_column not in df.columns:
        raise ValueError(f"DataFrame is missing target column '{target_column}'")
    y = df[target_column].astype(int).to_numpy()
    return X, y


__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_COLUMNS",
    "FeatureSchema",
    "NON_FEATURE_COLUMNS",
    "NUMERIC_FEATURES",
    "build_preprocessor",
    "split_features_target",
]
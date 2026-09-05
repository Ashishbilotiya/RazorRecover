"""Phase 2 ML tests.

Covers (per the user's Phase 2 brief):
    1. Dataset generation
    2. Feature preprocessing
    3. Model training
    4. Model persistence/loading
    5. Probability prediction
    6. Probability range [0, 1]
    7. Revenue-at-risk calculation
    8. Evaluation metrics
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from backend.ml import inference as inference_mod
from backend.ml.evaluation import (
    compute_business_metrics,
    compute_classification_metrics,
    evaluate,
    print_report,
)
from backend.ml.features import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    FeatureSchema,
    build_preprocessor,
    split_features_target,
)
from backend.ml.model import TrainConfig, build_pipeline, train

from data.generate_data import generate_dataset


# ---------------------------------------------------------------------------
# 1. Dataset generation
# ---------------------------------------------------------------------------
def test_generate_dataset_returns_dataframe_with_expected_columns():
    df = generate_dataset(n_rows=500, seed=7)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 500
    for col in FEATURE_COLUMNS:
        assert col in df.columns
    assert "recoverable" in df.columns
    assert df["recoverable"].isin([0, 1]).all()


def test_generate_dataset_is_deterministic():
    df_a = generate_dataset(n_rows=300, seed=123)
    df_b = generate_dataset(n_rows=300, seed=123)
    pd.testing.assert_frame_equal(df_a, df_b)


def test_dataset_features_carry_logical_signal():
    """Recoverable rows should have higher customer_success_rate on average."""
    df = generate_dataset(n_rows=5000, seed=11)
    recoverable = df[df["recoverable"] == 1]
    non_recoverable = df[df["recoverable"] == 0]
    assert recoverable["customer_success_rate"].mean() > non_recoverable[
        "customer_success_rate"
    ].mean()
    assert recoverable["previous_retry_count"].mean() < non_recoverable[
        "previous_retry_count"
    ].mean()


# ---------------------------------------------------------------------------
# 2. Feature preprocessing
# ---------------------------------------------------------------------------
def test_build_preprocessor_handles_numeric_and_categorical():
    preprocessor = build_preprocessor()
    df = generate_dataset(n_rows=200, seed=5)
    X, _ = split_features_target(df)
    transformed = preprocessor.fit_transform(X)
    # One-hot expands categoricals (2 cols × 5 methods + 7 reasons ≈ up to 12).
    assert transformed.shape[0] == len(X)
    assert transformed.shape[1] >= len(NUMERIC_FEATURES)


def test_split_features_target_separates_label_correctly():
    df = generate_dataset(n_rows=100, seed=2)
    X, y = split_features_target(df)
    assert list(X.columns) == list(FEATURE_COLUMNS)
    assert y.shape == (100,)
    assert set(np.unique(y)).issubset({0, 1})


def test_split_features_target_raises_on_missing_columns():
    df = pd.DataFrame({"amount": [1, 2, 3], "recoverable": [0, 1, 0]})
    with pytest.raises(ValueError, match="missing required feature"):
        split_features_target(df)


def test_feature_schema_canonical_order_is_stable():
    schema = FeatureSchema()
    expected = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    assert schema.all == expected


# ---------------------------------------------------------------------------
# 3. Model training
# ---------------------------------------------------------------------------
def test_train_produces_fitted_pipeline_and_report(tmp_path):
    df = generate_dataset(n_rows=1000, seed=21)
    config = TrainConfig(
        model_path=tmp_path / "recovery_model.pkl",
        decision_thresholds=(0.3, 0.5, 0.7),
    )
    result = train(df, config=config)

    assert isinstance(result.pipeline, Pipeline)
    # Stratified split should preserve class balance roughly.
    assert result.n_train + result.n_test == 1000

    report_text = print_report(result.report)
    assert "Precision" in report_text
    assert "ROC-AUC" in report_text
    assert "Revenue at Risk" in report_text


def test_train_persists_artifact_with_required_keys(tmp_path):
    df = generate_dataset(n_rows=500, seed=33)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    payload = joblib.load(config.model_path)
    for key in {"pipeline", "schema", "decision_thresholds", "model_version"}:
        assert key in payload


# ---------------------------------------------------------------------------
# 4. Model persistence / loading
# ---------------------------------------------------------------------------
def test_load_model_caches_and_round_trips(tmp_path):
    df = generate_dataset(n_rows=500, seed=99)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    inference_mod.reset_model_cache()
    artifact_a = inference_mod.load_model(config.model_path)
    artifact_b = inference_mod.load_model(config.model_path)
    assert artifact_a is artifact_b  # cached


def test_load_model_raises_when_missing(tmp_path):
    inference_mod.reset_model_cache()
    with pytest.raises(FileNotFoundError):
        inference_mod.load_model(tmp_path / "missing.pkl")


# ---------------------------------------------------------------------------
# 5 & 6. Probability prediction + range [0, 1]
# ---------------------------------------------------------------------------
def _reference_transaction() -> dict:
    """One well-formed transaction matching the feature schema."""
    return {
        "amount": 500_000,
        "customer_transaction_count": 12,
        "customer_success_rate": 0.92,
        "customer_failure_rate": 0.08,
        "customer_total_spend": 75_000.0,
        "average_order_value": 6_250.0,
        "previous_retry_count": 0,
        "time_since_last_success": 3,
        "hour_of_day": 14,
        "day_of_week": 3,
        "merchant_success_rate": 0.94,
        "payment_method_success_rate": 0.93,
        "recent_failure_rate": 0.10,
        "payment_method": "upi",
        "failure_reason": "temporary_timeout",
    }


def test_predict_recovery_returns_required_fields(tmp_path):
    df = generate_dataset(n_rows=800, seed=17)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    inference_mod.reset_model_cache()
    prediction = inference_mod.predict_recovery(
        _reference_transaction(), model_path=config.model_path
    )

    assert hasattr(prediction, "recovery_probability")
    assert hasattr(prediction, "revenue_at_risk")
    payload = prediction.to_dict()
    assert set(payload.keys()) == {"recovery_probability", "revenue_at_risk"}


def test_predict_recovery_probability_in_unit_interval(tmp_path):
    df = generate_dataset(n_rows=800, seed=17)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    inference_mod.reset_model_cache()

    rng = np.random.default_rng(0)
    for _ in range(50):
        tx = _reference_transaction()
        tx["amount"] = int(rng.integers(50_000, 1_000_000))
        tx["customer_success_rate"] = float(rng.uniform(0.1, 0.99))
        tx["customer_failure_rate"] = float(rng.uniform(0.0, 0.5))
        tx["previous_retry_count"] = int(rng.integers(0, 5))
        tx["payment_method"] = str(rng.choice(["card", "upi", "netbanking", "wallet", "emi"]))
        tx["failure_reason"] = str(
            rng.choice(
                [
                    "temporary_timeout",
                    "card_declined",
                    "user_cancelled",
                    "insufficient_funds",
                ]
            )
        )
        pred = inference_mod.predict_recovery(tx, model_path=config.model_path)
        assert 0.0 <= pred.recovery_probability <= 1.0


def test_predict_recovery_revenue_at_risk_formula(tmp_path):
    df = generate_dataset(n_rows=400, seed=8)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    inference_mod.reset_model_cache()
    tx = _reference_transaction()
    tx["amount"] = 100_000  # ₹1,000
    pred = inference_mod.predict_recovery(tx, model_path=config.model_path)
    expected = (100_000 / 100.0) * pred.recovery_probability
    assert pred.revenue_at_risk == pytest.approx(expected, rel=1e-9)


def test_predict_recovery_batch_returns_one_per_row(tmp_path):
    df = generate_dataset(n_rows=600, seed=44)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    inference_mod.reset_model_cache()
    batch = [_reference_transaction() for _ in range(5)]
    predictions = inference_mod.predict_recovery_batch(batch, model_path=config.model_path)
    assert len(predictions) == 5
    for pred in predictions:
        assert 0.0 <= pred.recovery_probability <= 1.0


def test_predict_recovery_raises_when_feature_missing(tmp_path):
    df = generate_dataset(n_rows=400, seed=12)
    config = TrainConfig(model_path=tmp_path / "recovery_model.pkl")
    train(df, config=config)

    inference_mod.reset_model_cache()
    bad_tx = _reference_transaction()
    bad_tx.pop("payment_method")
    with pytest.raises(ValueError, match="payment_method"):
        inference_mod.predict_recovery(bad_tx, model_path=config.model_path)


# ---------------------------------------------------------------------------
# 7. Evaluation metrics
# ---------------------------------------------------------------------------
def test_compute_classification_metrics_basic():
    y_true = np.array([0, 1, 1, 0, 1, 0])
    y_proba = np.array([0.1, 0.8, 0.6, 0.4, 0.9, 0.2])
    metrics = compute_classification_metrics(y_true, y_proba)
    assert 0.0 <= metrics.precision <= 1.0
    assert 0.0 <= metrics.recall <= 1.0
    assert 0.0 <= metrics.f1 <= 1.0
    assert 0.0 <= metrics.roc_auc <= 1.0
    assert sum(metrics.confusion_matrix[0] + metrics.confusion_matrix[1]) == len(y_true)


def test_compute_business_metrics_returns_one_per_threshold():
    amounts = np.array([100.0, 200.0, 300.0, 400.0, 500.0])
    y_true = np.array([0, 1, 1, 0, 1])
    y_proba = np.array([0.1, 0.9, 0.6, 0.4, 0.95])

    business = compute_business_metrics(
        amounts=amounts,
        y_true=y_true,
        y_proba=y_proba,
        thresholds=[0.3, 0.5, 0.8],
    )
    assert len(business) == 3

    high_threshold = [b for b in business if b.threshold == 0.8][0]
    assert high_threshold.n_targeted == 2  # proba 0.9 and 0.95

    for b in business:
        assert b.revenue_at_risk > 0
        assert b.revenue_targeted >= 0
        assert 0.0 <= b.recovery_rate <= 1.0
        assert 0.0 <= b.successful_recovery_rate <= 1.0
        assert 0.0 <= b.false_intervention_rate <= 1.0


def test_evaluate_combines_classification_and_business():
    amounts = np.array([100.0, 200.0, 300.0, 400.0])
    y_true = np.array([0, 1, 1, 0])
    y_proba = np.array([0.2, 0.7, 0.6, 0.4])
    report = evaluate(
        amounts=amounts, y_true=y_true, y_proba=y_proba, thresholds=[0.5]
    )
    assert report.classification.roc_auc >= 0.0
    assert len(report.business) == 1
    rendered = print_report(report)
    assert "Classification" in rendered
    assert "Business" in rendered
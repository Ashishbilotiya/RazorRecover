

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from backend.ml.evaluation import EvaluationReport, evaluate, print_report
from backend.ml.features import (
    FeatureSchema,
    build_preprocessor,
    split_features_target,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[2] / "models" / "recovery_model.pkl"
)
DEFAULT_DATASET = (
    Path(__file__).resolve().parents[2] / "data" / "synthetic_transactions.csv"
)


@dataclass
class TrainConfig:
    test_size: float = 0.2
    random_state: int = 42
    model_path: Path = DEFAULT_MODEL_PATH
    decision_thresholds: tuple[float, ...] = (0.3, 0.5, 0.7)


def build_pipeline(schema: FeatureSchema | None = None) -> Pipeline:
    """Compose the training pipeline (preprocessor + classifier)."""
    schema = schema or FeatureSchema()
    return Pipeline(
        steps=[
            ("preprocess", build_preprocessor(schema)),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1000,
                    solver="lbfgs",
                    random_state=42,
                ),
            ),
        ]
    )


@dataclass
class TrainingResult:
    pipeline: Pipeline
    report: EvaluationReport
    model_path: Path
    n_train: int
    n_test: int


def train(
    df: pd.DataFrame,
    config: TrainConfig | None = None,
    schema: FeatureSchema | None = None,
) -> TrainingResult:
    """Train, evaluate, and persist the recovery model."""
    config = config or TrainConfig()
    schema = schema or FeatureSchema()

    X, y = split_features_target(df, schema=schema)
    amounts = df["amount"].to_numpy(dtype=np.float64)

    X_train, X_test, y_train, y_test, amounts_train, amounts_test = train_test_split(
        X,
        y,
        amounts,
        test_size=config.test_size,
        random_state=config.random_state,
        stratify=y,
    )

    pipeline = build_pipeline(schema)
    pipeline.fit(X_train, y_train)

    y_proba = pipeline.predict_proba(X_test)[:, 1]

    report = evaluate(
        amounts=amounts_test,
        y_true=y_test,
        y_proba=y_proba,
        thresholds=list(config.decision_thresholds),
    )

    config.model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": pipeline,
            "schema": schema,
            "decision_thresholds": list(config.decision_thresholds),
            "model_version": "logreg-baseline-v1",
        },
        config.model_path,
    )
    logger.info("Saved model to %s", config.model_path)

    return TrainingResult(
        pipeline=pipeline,
        report=report,
        model_path=config.model_path,
        n_train=len(X_train),
        n_test=len(X_test),
    )


def load_data(dataset_path: Path = DEFAULT_DATASET) -> pd.DataFrame:
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {dataset_path}. Run `python -m data.generate_data`."
        )
    return pd.read_csv(dataset_path)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    df = load_data(args.dataset)
    config = TrainConfig(
        test_size=args.test_size,
        random_state=args.seed,
        model_path=args.model_out,
    )
    result = train(df, config=config)
    print(
        f"Trained on {result.n_train:,} rows; evaluated on {result.n_test:,} rows."
    )
    print(f"Model artifact: {result.model_path}")
    print()
    print(print_report(result.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

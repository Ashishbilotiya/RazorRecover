
from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "synthetic_transactions.csv"
DEFAULT_N_ROWS = 10_000
DEFAULT_SEED = 42

PAYMENT_METHODS = ["card", "upi", "netbanking", "wallet", "emi"]
FAILURE_REASONS = [
    "temporary_timeout",
    "gateway_degradation",
    "insufficient_funds",
    "authentication_failed",
    "card_declined",
    "user_cancelled",
    "network_error",
]

# Recoverable reasons carry higher base recoverability.
RECOVERABILITY_BY_REASON = {
    "temporary_timeout": 0.90,
    "network_error": 0.85,
    "gateway_degradation": 0.80,
    "authentication_failed": 0.55,
    "insufficient_funds": 0.40,
    "user_cancelled": 0.20,
    "card_declined": 0.15,
}

# Method-specific baseline recoverability (UPI retries well, cards decline hard).
METHOD_BASE_RECOVERABILITY = {
    "upi": 0.80,
    "wallet": 0.65,
    "netbanking": 0.55,
    "emi": 0.50,
    "card": 0.45,
}

# How forgiving the merchant / customer / failure combo is, used as a multiplier
# in the final logistic decision.
CUSTOMER_QUALITY_BIAS = {
    "good": 1.20,
    "average": 1.00,
    "poor": 0.85,
}


@dataclass(frozen=True)
class CustomerProfile:
    """A long-lived customer archetype used for repeated sampling."""

    external_id: str
    quality: str  # good | average | poor
    total_transactions: int
    successful_transactions: int
    failed_transactions: int
    total_spend: float  # in INR (rupees)
    last_successful_payment: datetime


def _seed_rng(seed: int) -> tuple[random.Random, np.random.Generator]:
    py_rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    return py_rng, np_rng


def _build_customer_pool(py_rng: random.Random, np_rng: np.random.Generator, n_customers: int) -> list[CustomerProfile]:
    """Generate `n_customers` archetypes with realistic distribution."""
    pool: list[CustomerProfile] = []
    now = datetime.now(timezone.utc)
    for i in range(n_customers):
        roll = py_rng.random()
        if roll < 0.6:
            quality = "good"
            success_rate = float(np_rng.uniform(0.85, 0.99))
        elif roll < 0.9:
            quality = "average"
            success_rate = float(np_rng.uniform(0.55, 0.85))
        else:
            quality = "poor"
            success_rate = float(np_rng.uniform(0.10, 0.55))

        total_tx = int(np_rng.integers(low=2, high=60))
        successful = int(round(total_tx * success_rate))
        failed = max(total_tx - successful, 0)
        total_spend = float(np_rng.uniform(500.0, 250_000.0))
        days_since_last = int(np_rng.integers(1, 180))
        last_success = now - timedelta(days=days_since_last)

        pool.append(
            CustomerProfile(
                external_id=f"cust_{i:05d}",
                quality=quality,
                total_transactions=total_tx,
                successful_transactions=successful,
                failed_transactions=failed,
                total_spend=total_spend,
                last_successful_payment=last_success,
            )
        )
    return pool


def _sample_failure(np_rng: np.random.Generator) -> str:
    return str(np_rng.choice(FAILURE_REASONS))


def _sample_method(np_rng: np.random.Generator) -> str:
    return str(np_rng.choice(PAYMENT_METHODS))


def _compute_recovery_probability(
    *,
    failure_reason: str,
    payment_method: str,
    customer_success_rate: float,
    customer_failure_rate: float,
    previous_retry_count: int,
    recent_failure_rate: float,
    merchant_success_rate: float,
    payment_method_success_rate: float,
    hour_of_day: int,
) -> float:
    """Compose a recoverable-probability score from observed features.

    Returns a value in ``[0, 1]``. The relationship is non-random by design:
    recoverable cases cluster around temporary failures + good customers +
    few retries; non-recoverable cases cluster around permanent declines +
    poor customers + many retries.
    """
    base = RECOVERABILITY_BY_REASON[failure_reason]
    method_bias = METHOD_BASE_RECOVERABILITY[payment_method]

    # Sigmoid blend over customer + system signals.
    z = 0.0
    z += 3.5 * (customer_success_rate - 0.5)            # +0..+1.75
    z += -2.5 * customer_failure_rate                  # -0..-1.25
    z += -2.5 * recent_failure_rate                    # -0..-1.25
    z += -1.5 * math.tanh(previous_retry_count / 2.0)  # plateaus around -1.5
    z += 1.0 * (merchant_success_rate - 0.85)          # +/-0.15
    z += 1.0 * (payment_method_success_rate - 0.85)
    z += 0.4 * math.cos((hour_of_day - 14) / 24.0 * 2 * math.pi)

    recovery_p = base * method_bias * CUSTOMER_QUALITY_BIAS["average"]
    # Modulate base by sigmoid (centered around 0) — keep [0, 1].
    recovery_p = min(max(recovery_p + 0.10 * math.tanh(z), 0.02), 0.98)
    return float(recovery_p)


def generate_dataset(
    n_rows: int = DEFAULT_N_ROWS,
    seed: int = DEFAULT_SEED,
    n_customers: int | None = None,
) -> pd.DataFrame:
    """Build the synthetic dataset deterministically."""
    py_rng, np_rng = _seed_rng(seed)
    n_customers = n_customers or max(500, n_rows // 20)

    pool = _build_customer_pool(py_rng, np_rng, n_customers)
    merchant_success_rate = float(np_rng.uniform(0.78, 0.96))

    # Pre-compute per-method success rates for ``payment_method_success_rate``.
    method_success_rate = {
        method: float(np_rng.uniform(0.70, 0.98))
        for method in PAYMENT_METHODS
    }

    rows: list[dict] = []
    for _ in range(n_rows):
        customer = pool[int(np_rng.integers(0, len(pool)))]
        payment_method = _sample_method(np_rng)
        failure_reason = _sample_failure(np_rng)

        amount = int(np_rng.integers(50_000, 500_000_00))  # paise: ₹500..₹500,000
        previous_retry_count = int(np_rng.integers(0, 6))
        hour = int(np_rng.integers(0, 24))
        day = int(np_rng.integers(0, 7))

        success_rate = (
            customer.successful_transactions / customer.total_transactions
            if customer.total_transactions
            else 0.5
        )
        failure_rate = (
            customer.failed_transactions / customer.total_transactions
            if customer.total_transactions
            else 0.5
        )
        aov = (
            customer.total_spend / customer.total_transactions
            if customer.total_transactions
            else 0.0
        )
        time_since_last_success = (
            datetime.now(timezone.utc) - customer.last_successful_payment
        ).days

        # Recent failure rate (last 5 tx) — correlated with overall failure rate.
        recent_failure_rate = float(np.clip(
            failure_rate + np_rng.normal(0, 0.10), 0.0, 1.0
        ))

        prob = _compute_recovery_probability(
            failure_reason=failure_reason,
            payment_method=payment_method,
            customer_success_rate=success_rate,
            customer_failure_rate=failure_rate,
            previous_retry_count=previous_retry_count,
            recent_failure_rate=recent_failure_rate,
            merchant_success_rate=merchant_success_rate,
            payment_method_success_rate=method_success_rate[payment_method],
            hour_of_day=hour,
        )

        # Stochastic label so evaluation ROC-AUC is meaningful; the underlying
        # probability still drives the distribution.
        recoverable_label = int(np_rng.random() < prob)

        rows.append(
            {
                "transaction_id": f"tx_{len(rows):06d}",
                "amount": amount,
                "payment_method": payment_method,
                "failure_reason": failure_reason,
                "customer_id": customer.external_id,
                "customer_transaction_count": customer.total_transactions,
                "customer_success_rate": round(success_rate, 4),
                "customer_failure_rate": round(failure_rate, 4),
                "customer_total_spend": round(customer.total_spend, 2),
                "average_order_value": round(aov, 2),
                "previous_retry_count": previous_retry_count,
                "time_since_last_success": time_since_last_success,
                "hour_of_day": hour,
                "day_of_week": day,
                "merchant_success_rate": round(merchant_success_rate, 4),
                "payment_method_success_rate": round(
                    method_success_rate[payment_method], 4
                ),
                "recent_failure_rate": round(recent_failure_rate, 4),
                "recoverable": recoverable_label,
                "recovery_probability": round(prob, 4),
            }
        )

    return pd.DataFrame(rows)


def write_dataset(df: pd.DataFrame, output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    return output


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_N_ROWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    df = generate_dataset(n_rows=args.rows, seed=args.seed)
    output = write_dataset(df, args.output)
    positives = int(df["recoverable"].sum())
    print(
        f"Wrote {len(df):,} rows to {output} "
        f"(recoverable={positives:,} / {len(df):,}, "
        f"~{positives / len(df):.1%})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

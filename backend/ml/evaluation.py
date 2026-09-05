"""Model + business evaluation for the recovery model.

Reports:
    - Precision, Recall, F1, ROC-AUC, Confusion Matrix
    - Revenue at Risk, Revenue Targeted, Estimated Recoverable Revenue
    - Confusion matrix per business threshold

The functions return dataclasses so tests can assert on values directly;
``print_report`` formats a human-readable summary.

See CLAUDE.md sections 13, 31.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class ClassificationMetrics:
    precision: float
    recall: float
    f1: float
    roc_auc: float
    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int

    @property
    def confusion_matrix(self) -> list[list[int]]:
        return [
            [self.true_negatives, self.false_positives],
            [self.false_negatives, self.true_positives],
        ]


@dataclass
class BusinessMetrics:
    """Business-aligned aggregates evaluated at a decision threshold.

    All amounts are in INR (rupees), converted from the dataset's paise.
    """

    threshold: float
    revenue_at_risk: float
    revenue_targeted: float
    estimated_recoverable_revenue: float
    recovery_rate: float
    successful_recovery_rate: float
    false_intervention_rate: float
    n_targeted: int
    revenue_currency: str = "INR"

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "revenue_at_risk": self.revenue_at_risk,
            "revenue_targeted": self.revenue_targeted,
            "estimated_recoverable_revenue": self.estimated_recoverable_revenue,
            "recovery_rate": self.recovery_rate,
            "successful_recovery_rate": self.successful_recovery_rate,
            "false_intervention_rate": self.false_intervention_rate,
            "n_targeted": self.n_targeted,
            "revenue_currency": self.revenue_currency,
        }


@dataclass
class EvaluationReport:
    classification: ClassificationMetrics
    business: list[BusinessMetrics] = field(default_factory=list)


def compute_classification_metrics(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    threshold: float = 0.5,
) -> ClassificationMetrics:
    """Standard ML metrics on a held-out set."""
    y_pred = (y_proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    return ClassificationMetrics(
        precision=float(precision_score(y_true, y_pred, zero_division=0)),
        recall=float(recall_score(y_true, y_pred, zero_division=0)),
        f1=float(f1_score(y_true, y_pred, zero_division=0)),
        roc_auc=float(roc_auc_score(y_true, y_proba)),
        true_negatives=int(tn),
        false_positives=int(fp),
        false_negatives=int(fn),
        true_positives=int(tp),
    )


def compute_business_metrics(
    *,
    amounts: np.ndarray,
    y_true: np.ndarray,
    y_proba: np.ndarray,
    thresholds: list[float] | None = None,
    paise_to_rupees: float = 100.0,
) -> list[BusinessMetrics]:
    """Compute business metrics at one or more decision thresholds.

    ``amounts`` are expected to be in paise (the dataset's unit); they're
    converted to INR via ``paise_to_rupees`` so the dashboard reads naturally.

    Definitions follow CLAUDE.md section 31:
        - Revenue at Risk       = sum(amount × recovery_probability)
        - Revenue Targeted      = sum(amount for cases above threshold)
        - Estimated Recoverable = sum(amount for cases predicted positive AND
                                       truly recoverable)
        - Recovery Rate         = Estimated Recoverable / Revenue Targeted
        - Successful Rate       = true positives / positives predicted
        - False Intervention    = false positives / positives predicted
    """
    thresholds = thresholds or [0.5]
    amounts_rupees = amounts / paise_to_rupees

    revenue_at_risk_total = float(np.sum(amounts_rupees * y_proba))

    out: list[BusinessMetrics] = []
    for threshold in thresholds:
        predicted_positive = y_proba >= threshold
        targeted = amounts_rupees[predicted_positive]
        revenue_targeted = float(np.sum(targeted))
        n_targeted = int(np.sum(predicted_positive))

        if n_targeted == 0:
            out.append(
                BusinessMetrics(
                    threshold=threshold,
                    revenue_at_risk=revenue_at_risk_total,
                    revenue_targeted=0.0,
                    estimated_recoverable_revenue=0.0,
                    recovery_rate=0.0,
                    successful_recovery_rate=0.0,
                    false_intervention_rate=0.0,
                    n_targeted=0,
                )
            )
            continue

        true_recoverable = y_true.astype(bool)
        tp_mask = predicted_positive & true_recoverable
        fp_mask = predicted_positive & ~true_recoverable

        estimated_recoverable = float(np.sum(amounts_rupees[tp_mask]))
        tp = int(np.sum(tp_mask))
        fp = int(np.sum(fp_mask))
        recovery_rate = estimated_recoverable / revenue_targeted if revenue_targeted else 0.0
        successful_recovery_rate = tp / (tp + fp) if (tp + fp) else 0.0
        false_intervention_rate = fp / (tp + fp) if (tp + fp) else 0.0

        out.append(
            BusinessMetrics(
                threshold=threshold,
                revenue_at_risk=revenue_at_risk_total,
                revenue_targeted=revenue_targeted,
                estimated_recoverable_revenue=estimated_recoverable,
                recovery_rate=float(recovery_rate),
                successful_recovery_rate=float(successful_recovery_rate),
                false_intervention_rate=float(false_intervention_rate),
                n_targeted=n_targeted,
            )
        )
    return out


def evaluate(
    *,
    amounts: np.ndarray,
    y_true: np.ndarray,
    y_proba: np.ndarray,
    thresholds: list[float] | None = None,
    paise_to_rupees: float = 100.0,
) -> EvaluationReport:
    """Compute classification + business metrics in one call."""
    classification = compute_classification_metrics(y_true, y_proba)
    business = compute_business_metrics(
        amounts=amounts,
        y_true=y_true,
        y_proba=y_proba,
        thresholds=thresholds,
        paise_to_rupees=paise_to_rupees,
    )
    return EvaluationReport(classification=classification, business=business)


def print_report(report: EvaluationReport) -> str:
    """Format a concise evaluation report. Returns the rendered string."""
    lines: list[str] = []
    cls = report.classification
    lines.append("=== Classification (held-out test set) ===")
    lines.append(f"  Precision : {cls.precision:.4f}")
    lines.append(f"  Recall    : {cls.recall:.4f}")
    lines.append(f"  F1        : {cls.f1:.4f}")
    lines.append(f"  ROC-AUC   : {cls.roc_auc:.4f}")
    lines.append(
        f"  Confusion : "
        f"TN={cls.true_negatives}  FP={cls.false_positives}  "
        f"FN={cls.false_negatives}  TP={cls.true_positives}"
    )
    lines.append("")
    lines.append("=== Business metrics ===")
    for b in report.business:
        lines.append(f"  threshold={b.threshold:.2f}")
        lines.append(f"    Revenue at Risk       : ₹{b.revenue_at_risk:,.0f}")
        lines.append(f"    Revenue Targeted      : ₹{b.revenue_targeted:,.0f}")
        lines.append(
            f"    Estimated Recoverable : ₹{b.estimated_recoverable_revenue:,.0f}"
        )
        lines.append(f"    Recovery Rate         : {b.recovery_rate:.2%}")
        lines.append(f"    Successful Rate       : {b.successful_recovery_rate:.2%}")
        lines.append(f"    False Intervention    : {b.false_intervention_rate:.2%}")
        lines.append(f"    Cases Targeted        : {b.n_targeted:,}")
    return "\n".join(lines)


__all__ = [
    "BusinessMetrics",
    "ClassificationMetrics",
    "EvaluationReport",
    "compute_business_metrics",
    "compute_classification_metrics",
    "evaluate",
    "print_report",
]
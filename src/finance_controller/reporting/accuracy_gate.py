from __future__ import annotations

from finance_controller.models import AccuracyMetrics


def failing_metric(accuracy: AccuracyMetrics, threshold: float) -> str | None:
    for name in ("precision", "recall", "f1"):
        if float(getattr(accuracy, name)) < threshold:
            return name
    return None

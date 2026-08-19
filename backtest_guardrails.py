from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class Guardrails:
    min_history_years: float = 5.0
    min_samples: int = 100
    min_win_rate: float = 0.55
    min_expected_value_pct: float = 0.002
    max_stop_pct: float = 0.015
    max_new_stock_weight: float = 0.70


def eligible(summary: dict, guard: Guardrails = Guardrails()) -> tuple[bool, list[str]]:
    reasons = []
    if summary.get("history_years", 0) < guard.min_history_years:
        reasons.append("insufficient direct history")
    if summary.get("samples", 0) < guard.min_samples:
        reasons.append("insufficient comparable setups")
    if summary.get("win_rate", 0) < guard.min_win_rate:
        reasons.append("win rate below threshold")
    if summary.get("expected_value", 0) < guard.min_expected_value_pct:
        reasons.append("expected value below threshold")
    if summary.get("stop_pct", 0) > guard.max_stop_pct:
        reasons.append("stop risk above threshold")
    return not reasons, reasons

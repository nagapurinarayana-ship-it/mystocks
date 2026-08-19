from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class HistoryTier:
    name: str
    min_years: float
    max_confidence: float

HISTORY_TIERS = (
    HistoryTier("long", 5.0, 1.0),
    HistoryTier("medium", 3.0, 0.85),
    HistoryTier("short", 1.0, 0.70),
    HistoryTier("new", 0.5, 0.50),
)


def history_tier(years: float) -> HistoryTier:
    for tier in HISTORY_TIERS:
        if years >= tier.min_years:
            return tier
    return HistoryTier("insufficient", 0.0, 0.0)


def research_weight(years: float, sample_count: int) -> float:
    """Reduce confidence for newer listings without excluding them entirely."""
    tier = history_tier(years)
    if tier.name == "insufficient" or sample_count < 20:
        return 0.0
    sample_factor = min(1.0, sample_count / 200.0)
    return tier.max_confidence * sample_factor

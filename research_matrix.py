from __future__ import annotations

import pandas as pd
from research_policy import history_tier, research_weight


def score_research_candidate(df: pd.DataFrame, setup_probability: float, samples: int) -> dict:
    if df.empty:
        years = 0.0
    else:
        days = max(0, (df.index.max() - df.index.min()).days)
        years = days / 365.25
    tier = history_tier(years)
    weight = research_weight(years, samples)
    return {
        "history_years": round(years, 2),
        "history_tier": tier.name,
        "raw_probability": setup_probability,
        "research_weight": round(weight, 4),
        "weighted_probability": round(setup_probability * weight, 4),
        "samples": samples,
    }

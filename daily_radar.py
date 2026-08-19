from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable
import math
import pandas as pd
from engine import features, outcome
from config import StrategyConfig
from research_policy import history_tier, research_weight
from selection import SelectionConfig, select_candidates

@dataclass
class Candidate:
    symbol: str
    entry: float
    target: float
    stop: float
    probability: float
    lower_bound: float
    samples: int
    history_years: float
    history_tier: str
    expected_value: float
    score: float
    status: str

def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0: return 0.0
    p = wins / n
    d = 1 + z*z/n
    centre = p + z*z/(2*n)
    margin = z * math.sqrt((p*(1-p) + z*z/(4*n))/n)
    return max(0.0, (centre-margin)/d)

def historical_probability(df: pd.DataFrame, cfg: StrategyConfig) -> tuple[float, float, int, int]:
    x = features(df)
    wins = resolved = 0
    for i in range(len(x)):
        if not bool(x.iloc[i]["signal"]): continue
        r = outcome(x, i, cfg)
        if r in {"win", "loss"}:
            resolved += 1
            wins += r == "win"
    return (wins/resolved if resolved else 0.0, wilson_lower(wins, resolved), resolved, wins)

def rank_daily(universe: dict[str, pd.DataFrame], cfg: StrategyConfig) -> list[Candidate]:
    selection_cfg = SelectionConfig(
        max_picks=cfg.top_n,
        min_samples=cfg.min_samples,
        min_lower_bound=cfg.min_probability_lower95,
        min_expected_value=cfg.min_expected_value,
    )
    candidates: list[Candidate] = []
    for symbol, df in universe.items():
        if len(df) < 252: continue
        x = features(df)
        if x.empty or not bool(x.iloc[-1]["signal"]): continue
        p, lower, samples, _ = historical_probability(df, cfg)
        years = (df.index.max() - df.index.min()).days / 365.25
        tier = history_tier(years)
        weight = research_weight(years, samples)
        entry = float(df.iloc[-1]["Close"])
        target = entry * (1 + cfg.target_pct)
        stop = entry * (1 - cfg.stop_pct)
        expected_value = p * cfg.target_pct - (1 - p) * cfg.stop_pct - cfg.round_trip_cost_pct
        score = lower * weight * max(expected_value, 0.0)
        candidates.append(Candidate(symbol, entry, target, stop, p, lower, samples, years, tier.name, expected_value, score, "candidate"))
    return select_candidates(candidates, selection_cfg)

def to_frame(candidates: Iterable[Candidate]) -> pd.DataFrame:
    return pd.DataFrame([asdict(c) for c in candidates])

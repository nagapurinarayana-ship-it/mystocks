from __future__ import annotations

import math
from dataclasses import dataclass

@dataclass(frozen=True)
class RobustnessResult:
    samples: int
    win_rate: float
    expected_value: float
    lower_bound: float
    profit_factor: float
    max_drawdown: float
    positive_month_fraction: float
    passed: bool


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    d = 1 + z*z/n
    return max(0.0, (p + z*z/(2*n) - z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/d)


def summarize_returns(returns: list[float], min_samples: int = 50) -> RobustnessResult:
    n = len(returns)
    wins = sum(r > 0 for r in returns)
    win_rate = wins / n if n else 0.0
    avg = sum(returns) / n if n else 0.0
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = -sum(r for r in returns if r < 0)
    pf = gross_profit / gross_loss if gross_loss else float("inf")
    equity = 1.0
    peak = 1.0
    dd = 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        dd = min(dd, equity / peak - 1)
    passed = n >= min_samples and avg > 0 and wilson_lower(wins, n) > 0.5 and pf > 1
    return RobustnessResult(n, win_rate, avg, wilson_lower(wins, n), pf, dd, 0.0, passed)

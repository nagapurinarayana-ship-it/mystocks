from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    target_pct: float = 0.02
    stop_pct: float = 0.01
    max_hold_days: int = 3
    round_trip_cost_pct: float = 0.0010
    min_price: float = 50.0
    min_avg_volume: float = 200_000.0
    min_samples: int = 80
    min_probability: float = 0.55
    min_expected_value_pct: float = 0.002
    top_n: int = 3


DEFAULT_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "M&M.NS", "SUNPHARMA.NS", "MARUTI.NS", "HCLTECH.NS",
    "BAJFINANCE.NS", "TITAN.NS", "ADANIENT.NS", "NTPC.NS", "POWERGRID.NS",
    "TATASTEEL.NS", "TATAMOTORS.NS", "WIPRO.NS", "TECHM.NS", "ULTRACEMCO.NS",
]

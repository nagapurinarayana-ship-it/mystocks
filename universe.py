from __future__ import annotations

from pathlib import Path
import json

# Research universe is deliberately explicit. A future production universe must
# come from a point-in-time NSE constituent history to avoid survivorship bias.
UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "M&M.NS", "SUNPHARMA.NS", "MARUTI.NS", "HCLTECH.NS",
    "BAJFINANCE.NS", "TITAN.NS", "ADANIENT.NS", "NTPC.NS", "POWERGRID.NS",
    "TATASTEEL.NS", "TATAMOTORS.NS", "WIPRO.NS", "TECHM.NS", "ULTRACEMCO.NS",
]

METADATA_PATH = Path("data/universe_metadata.json")


def save_metadata(metadata: dict) -> None:
    METADATA_PATH.parent.mkdir(exist_ok=True)
    METADATA_PATH.write_text(json.dumps(metadata, indent=2))


def validate_universe() -> list[str]:
    # Keep this validation conservative until point-in-time constituent data is added.
    return sorted(set(UNIVERSE))

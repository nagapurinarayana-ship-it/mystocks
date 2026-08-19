from __future__ import annotations

import importlib

REQUIRED = ["pandas", "yfinance"]
for name in REQUIRED:
    importlib.import_module(name)
    print(f"OK: {name}")

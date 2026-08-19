from __future__ import annotations

from dataclasses import asdict
import pandas as pd
from config import StrategyConfig
from target_sweep import evaluate
from walk_forward import expanding_windows, select_on_train


def evaluate_walk_forward(df: pd.DataFrame, cfg: StrategyConfig, train_days: int = 756, test_days: int = 126, step_days: int = 126) -> pd.DataFrame:
    rows = []
    for fold, (train, test) in enumerate(expanding_windows(df, train_days, test_days, step_days), 1):
        selected = select_on_train(train, cfg)
        if not selected:
            continue
        result = evaluate(test, cfg, selected['target_pct'], selected['stop_pct'], int(selected['horizon']))
        row = asdict(result)
        row.update({
            'fold': fold,
            'train_start': train.index.min(),
            'train_end': train.index.max(),
            'test_start': test.index.min(),
            'test_end': test.index.max(),
            'selected_from_train_ev': selected['expected_value'],
        })
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate(folds: pd.DataFrame) -> dict:
    if folds.empty:
        return {'folds': 0, 'samples': 0, 'win_rate': 0.0, 'expected_value': 0.0, 'passed': False}
    samples = int(folds['samples'].sum())
    wins = int(folds['wins'].sum())
    ev = float((folds['expected_value'] * folds['samples']).sum() / samples) if samples else 0.0
    return {
        'folds': int(len(folds)),
        'samples': samples,
        'win_rate': wins / samples if samples else 0.0,
        'expected_value': ev,
        'passed': bool(ev > 0 and samples >= 50 and (wins / samples if samples else 0) > 0.5),
    }

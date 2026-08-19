from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class SelectionConfig:
    max_picks: int = 3
    min_samples: int = 50
    min_lower_bound: float = 0.45
    min_expected_value: float = 0.0
    max_emerging_share: float = 0.34


def select_candidates(candidates, cfg: SelectionConfig = SelectionConfig()):
    """Select up to max_picks without forcing weak candidates.

    Candidates are expected to expose lower_bound, samples, score, expected_value
    and history_tier. Emerging candidates are capped as a share of the shortlist.
    """
    eligible = [c for c in candidates
                if getattr(c, "samples", 0) >= cfg.min_samples
                and getattr(c, "lower_bound", 0.0) >= cfg.min_lower_bound
                and getattr(c, "expected_value", 0.0) >= cfg.min_expected_value]
    eligible.sort(key=lambda c: getattr(c, "score", 0.0), reverse=True)
    out, emerging = [], 0
    for c in eligible:
        if len(out) >= cfg.max_picks:
            break
        if getattr(c, "history_tier", "long") in {"short", "new"}:
            if emerging >= max(1, int(cfg.max_picks * cfg.max_emerging_share + 0.999)):
                continue
            emerging += 1
        out.append(c)
    return out

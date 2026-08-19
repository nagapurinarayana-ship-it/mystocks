# Candidate research schema

Every daily candidate should carry evidence, not just a ticker.

Required fields:

- symbol
- signal_date
- entry_range
- target_pct
- stop_pct
- expected_value
- direct_history_years
- history_tier
- direct_setup_samples
- direct_target_before_stop_probability
- lower_confidence_bound
- sector
- sector_relative_strength
- market_regime
- liquidity_score
- volatility_score
- peer_evidence
- confidence_label
- reasons
- invalidation_conditions

The UI should visibly distinguish `Established` and `Emerging` candidates.

An emerging candidate must not outrank an established candidate solely because its raw short-history win rate is higher.

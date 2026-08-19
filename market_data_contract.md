# Market-data contract

MyStocks now separates research logic from the data vendor.

## Required fields

For every symbol/date observation:

- symbol
- session_date
- open
- high
- low
- close
- volume
- adjusted_close (when vendor provides it)
- instrument_status
- listing_date
- delisting_date (when applicable)
- sector_at_date
- index_membership_at_date
- corporate_action_flags

## Quality checks

Reject or quarantine data when:

- OHLC is missing or non-positive
- high < max(open, close) or low > min(open, close)
- duplicate sessions exist
- timestamps are not normalized to India market dates
- a symbol has suspicious zero-volume gaps without an exchange explanation

Adjusted prices are useful for return research, but target/stop simulation must retain raw OHLC and corporate-action events so historical trade paths are not silently distorted.

## Provider policy

Prototype providers may be used for development. Final research should use a licensed/authoritative source with historical corporate actions and point-in-time universe information.

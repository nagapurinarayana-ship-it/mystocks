import pytest

from intraday.execution.configuration import (
    FeeConfigurationError,
    FEE_ENV_FIELDS,
    load_fee_schedule_from_environment,
)


def clear_fee_environment(monkeypatch):
    for suffix in FEE_ENV_FIELDS.values():
        monkeypatch.delenv(f"MYSTOCKS_PAPER_FEE_{suffix}", raising=False)


def configure_fee_environment(monkeypatch):
    values = {
        "BROKERAGE_RATE": "0.0001",
        "BROKERAGE_CAP": "20",
        "EXCHANGE_RATE": "0.00001",
        "SEBI_RATE": "0.000001",
        "GST_RATE": "0.18",
        "STT_SELL_RATE": "0.00025",
        "STAMP_BUY_RATE": "0.00003",
        "SLIPPAGE_BPS": "5",
    }
    for key, value in values.items():
        monkeypatch.setenv(f"MYSTOCKS_PAPER_FEE_{key}", value)


def test_fee_schedule_is_absent_when_no_broker_tariff_is_configured(monkeypatch):
    clear_fee_environment(monkeypatch)
    assert load_fee_schedule_from_environment() is None


def test_fee_schedule_rejects_partial_configuration(monkeypatch):
    clear_fee_environment(monkeypatch)
    monkeypatch.setenv("MYSTOCKS_PAPER_FEE_BROKERAGE_RATE", "0.0001")
    with pytest.raises(FeeConfigurationError, match="incomplete"):
        load_fee_schedule_from_environment()


def test_fee_schedule_loads_only_explicit_broker_values(monkeypatch):
    clear_fee_environment(monkeypatch)
    configure_fee_environment(monkeypatch)
    fees = load_fee_schedule_from_environment()
    assert fees is not None
    assert str(fees.brokerage_rate) == "0.0001"
    assert str(fees.slippage_bps) == "5"


def test_fee_schedule_rejects_invalid_rates(monkeypatch):
    clear_fee_environment(monkeypatch)
    configure_fee_environment(monkeypatch)
    monkeypatch.setenv("MYSTOCKS_PAPER_FEE_BROKERAGE_RATE", "-0.01")
    with pytest.raises(FeeConfigurationError, match="invalid"):
        load_fee_schedule_from_environment()

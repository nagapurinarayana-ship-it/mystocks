def test_backtest_cli_imports_without_starting_network_or_order_actions():
    import scripts.run_intraday_backtest as runner
    assert callable(runner.main)



def test_upstox_smoke_test_imports_without_network_or_broker_actions():
    import scripts.check_upstox_connection as runner

    assert callable(runner.main)
    assert runner.IST is not None



def test_upstox_smoke_test_fails_before_network_when_access_token_is_missing(monkeypatch, capsys):
    import sys
    import scripts.check_upstox_connection as runner

    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["check_upstox_connection.py"])
    assert runner.main() == 2
    output = capsys.readouterr().out
    assert "Missing UPSTOX_ACCESS_TOKEN" in output
    assert "unit-test-token" not in output

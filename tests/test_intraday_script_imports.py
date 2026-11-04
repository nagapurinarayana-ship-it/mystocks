def test_backtest_cli_imports_without_starting_network_or_order_actions():
    import scripts.run_intraday_backtest as runner
    assert callable(runner.main)



def test_upstox_smoke_test_imports_without_network_or_broker_actions():
    import scripts.check_upstox_connection as runner

    assert callable(runner.main)
    assert runner.IST is not None

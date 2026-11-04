def test_backtest_cli_imports_without_starting_network_or_order_actions():
    import scripts.run_intraday_backtest as runner
    assert callable(runner.main)

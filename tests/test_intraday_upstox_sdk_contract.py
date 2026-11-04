def test_installed_upstox_sdk_exposes_required_market_data_v3_methods():
    import upstox_client

    assert hasattr(upstox_client, "Configuration")
    assert hasattr(upstox_client, "ApiClient")
    assert hasattr(upstox_client, "MarketDataStreamerV3")

    streamer = upstox_client.MarketDataStreamerV3
    for method in ("connect", "disconnect", "on", "auto_reconnect"):
        assert callable(getattr(streamer, method, None)), method

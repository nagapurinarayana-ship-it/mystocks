def test_installed_upstox_sdk_exposes_required_market_data_v3_methods():
    import upstox_client

    assert hasattr(upstox_client, "Configuration")
    assert hasattr(upstox_client, "ApiClient")
    assert hasattr(upstox_client, "MarketDataStreamerV3")

    streamer = upstox_client.MarketDataStreamerV3
    for method in ("connect", "disconnect", "on", "auto_reconnect"):
        assert callable(getattr(streamer, method, None)), method



def test_upstox_sdk_v3_streamer_can_be_constructed_without_connecting():
    import upstox_client

    configuration = upstox_client.Configuration()
    configuration.access_token = "unit-test-token-not-used-for-network"
    api_client = upstox_client.ApiClient(configuration)
    streamer = upstox_client.MarketDataStreamerV3(
        api_client,
        ["NSE_EQ|INE002A01018"],
        "ltpc",
    )
    assert callable(streamer.connect)
    assert callable(streamer.disconnect)
    assert callable(streamer.on)
    assert callable(streamer.auto_reconnect)

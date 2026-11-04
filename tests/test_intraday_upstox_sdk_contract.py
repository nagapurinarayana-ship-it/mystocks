from datetime import datetime
from zoneinfo import ZoneInfo

from intraday.market_data.upstox_v3 import (
    UpstoxV3MarketDataClient,
    parse_upstox_v3_message,
)


def test_installed_upstox_sdk_exposes_the_v3_feed_protobuf_schema():
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2

    assert hasattr(MarketDataFeedV3_pb2, "FeedResponse")
    response = MarketDataFeedV3_pb2.FeedResponse()
    key = "NSE_EQ|INE002A01018"
    response.feeds[key].ltpc.ltp = 100.25
    response.feeds[key].ltpc.ltt = 1793763900000
    response.feeds[key].ltpc.ltq = 15
    wire = response.SerializeToString()

    decoded = UpstoxV3MarketDataClient.decode_protobuf_frame(wire)
    parsed = parse_upstox_v3_message(
        decoded,
        received_at=datetime(2026, 11, 4, 9, 15, 1, tzinfo=ZoneInfo("Asia/Kolkata")),
        symbol_by_key={key: "RELIANCE"},
    )
    assert len(parsed) == 1
    assert parsed[0].symbol == "RELIANCE"
    assert parsed[0].price == 100.25
    assert parsed[0].last_trade_quantity == 15


def test_actual_upstox_sdk_protobuf_frame_is_not_mistaken_for_json():
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2

    message = MarketDataFeedV3_pb2.FeedResponse()
    message.feeds["NSE_EQ|INE002A01018"].ltpc.ltp = 101
    message.feeds["NSE_EQ|INE002A01018"].ltpc.ltt = 1793763900000
    wire = message.SerializeToString()
    decoded = UpstoxV3MarketDataClient.decode_protobuf_frame(wire)
    assert "feeds" in decoded



def test_real_v3_protobuf_fullfeed_volume_and_depth_fields_parse_correctly():
    from datetime import datetime, timezone
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2

    key = "NSE_EQ|INE002A01018"
    message = MarketDataFeedV3_pb2.FeedResponse()
    full = message.feeds[key].fullFeed.marketFF
    full.ltpc.ltp = 100.5
    full.ltpc.ltt = 1793763900000
    full.ltpc.ltq = 25
    full.vtt = 987654
    quote = full.marketLevel.bidAskQuote.add()
    quote.bidP = 100.45
    quote.bidQ = 120
    quote.askP = 100.55
    quote.askQ = 90

    decoded = UpstoxV3MarketDataClient.decode_protobuf_frame(
        message.SerializeToString()
    )
    ticks = parse_upstox_v3_message(
        decoded,
        received_at=datetime(2026, 11, 4, 4, 30, 1, tzinfo=timezone.utc),
        symbol_by_key={key: "RELIANCE"},
    )
    assert len(ticks) == 1
    assert ticks[0].cumulative_volume == 987654
    assert ticks[0].best_bid == 100.45
    assert ticks[0].best_ask == 100.55
    assert ticks[0].best_bid_quantity == 120
    assert ticks[0].best_ask_quantity == 90

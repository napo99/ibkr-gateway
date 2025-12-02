"""Regression tests for data sanitization utilities."""
from datetime import datetime, timezone
import sys
import types

# Provide a lightweight ib_insync stub so tests don't require the real dependency.
if "ib_insync" not in sys.modules:
    class _DummyIB:
        def __init__(self, *_, **__): ...

    class _DummyFuture:
        def __init__(self, *_, **__): ...

    class _DummyUtil:
        @staticmethod
        def patchAsyncio():
            return None

    sys.modules["ib_insync"] = types.SimpleNamespace(IB=_DummyIB, Future=_DummyFuture, util=_DummyUtil())

from src.live_server import LiveDashboardServer
from src.data_sources import OHLCV
import pandas as pd


def test_bar_to_dict_filters_invalid_and_allows_valid():
    server = LiveDashboardServer()
    good_bar = OHLCV(
        timestamp=datetime.now(timezone.utc),
        open=10.0, high=11.0, low=9.5, close=10.5, volume=1000.0,
    )
    assert server._bar_to_dict(good_bar) is not None

    bad_bar = OHLCV(
        timestamp=datetime.now(timezone.utc),
        open=float("nan"), high=11.0, low=9.5, close=10.5, volume=1000.0,
    )
    assert server._bar_to_dict(bad_bar) is None


def test_clean_dataframe_drops_nonfinite_rows():
    server = LiveDashboardServer()
    df = pd.DataFrame(
        [
            {
                "timestamp": datetime.now(timezone.utc),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            },
            {
                "timestamp": datetime.now(timezone.utc),
                "open": float("nan"),
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            },
        ]
    )
    cleaned = server._clean_dataframe(df)
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["open"] == 1.0

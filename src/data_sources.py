"""
Data Sources - IBKR and Binance clients
Modular, compact, testable
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Optional
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
import websockets
import aiohttp
from ib_insync import IB, Future, util

# Configure ib_insync to work with existing event loop
util.patchAsyncio()


@dataclass
class OHLCV:
    """Single OHLCV bar"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {
            'time': int(self.timestamp.timestamp()),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }


@dataclass
class DataBuffer:
    """Thread-safe rolling buffer for OHLCV data"""
    max_bars: int = 500
    bars: list = field(default_factory=list)

    def add(self, bar: OHLCV):
        self.bars.append(bar)
        if len(self.bars) > self.max_bars:
            self.bars.pop(0)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.bars:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return pd.DataFrame([
            {'timestamp': b.timestamp, 'open': b.open, 'high': b.high,
             'low': b.low, 'close': b.close, 'volume': b.volume}
            for b in self.bars
        ])

    def to_json(self) -> list:
        return [b.to_dict() for b in self.bars]

    @property
    def last(self) -> Optional[OHLCV]:
        return self.bars[-1] if self.bars else None


class BinanceClient:
    """Binance WebSocket client for BTC/USDT"""

    WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
    REST_URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, on_bar: Optional[Callable[[OHLCV], None]] = None):
        self.buffer = DataBuffer()
        self.on_bar = on_bar
        self._running = False
        self._ws = None

    def _interval_ms(self, interval: str) -> int:
        """Convert Binance interval string to milliseconds (supports m/h)."""
        if interval.endswith('m'):
            return int(interval[:-1]) * 60_000
        if interval.endswith('h'):
            return int(interval[:-1]) * 3_600_000
        raise ValueError(f"Unsupported interval: {interval}")

    async def fetch_historical(self, interval: str = '1h', limit: int = 168) -> pd.DataFrame:
        """Fetch historical klines, chunking when limit > 1000 (Binance max)."""
        max_limit = 1000  # Binance per-request cap
        step_ms = self._interval_ms(interval)
        all_klines = []

        async with aiohttp.ClientSession() as session:
            if limit <= max_limit:
                params = {'symbol': 'BTCUSDT', 'interval': interval, 'limit': limit}
                async with session.get(self.REST_URL, params=params) as resp:
                    all_klines = await resp.json()
            else:
                # Pull in chronological chunks using startTime to avoid overlap
                now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
                start_ms = now_ms - step_ms * limit
                fetched = 0
                next_start = start_ms
                # prevent infinite loops
                for _ in range((limit // max_limit) + 5):
                    batch_limit = min(max_limit, limit - fetched)
                    params = {
                        'symbol': 'BTCUSDT',
                        'interval': interval,
                        'limit': batch_limit,
                        'startTime': next_start
                    }
                    async with session.get(self.REST_URL, params=params) as resp:
                        chunk = await resp.json()
                    if not chunk:
                        break
                    all_klines.extend(chunk)
                    fetched = len(all_klines)
                    # advance start to next candle open time
                    next_start = chunk[-1][0] + step_ms
                    if fetched >= limit or len(chunk) < batch_limit:
                        break

        # Trim to requested limit
        all_klines = all_klines[:limit]

        bars = []
        for k in all_klines:
            bars.append(OHLCV(
                timestamp=datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5])
            ))
        return pd.DataFrame([
            {'timestamp': b.timestamp, 'open': b.open, 'high': b.high,
             'low': b.low, 'close': b.close, 'volume': b.volume}
            for b in bars
        ])

    async def stream(self):
        """Stream real-time 1-min klines"""
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    self._ws = ws
                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        k = data.get('k', {})
                        if k.get('x'):  # Candle closed
                            bar = OHLCV(
                                timestamp=datetime.fromtimestamp(k['t'] / 1000, tz=timezone.utc),
                                open=float(k['o']),
                                high=float(k['h']),
                                low=float(k['l']),
                                close=float(k['c']),
                                volume=float(k['v'])
                            )
                            self.buffer.add(bar)
                            if self.on_bar:
                                self.on_bar(bar)
            except Exception as e:
                if self._running:
                    print(f"[BTC] WebSocket error: {e}, reconnecting...")
                    await asyncio.sleep(1)

    def stop(self):
        self._running = False


class IBKRClient:
    """IBKR client for ES/NQ futures"""

    def __init__(self, symbol: str = 'ES', host: str = '127.0.0.1',
                 port: int = 4002, client_id: int = 1,
                 on_bar: Optional[Callable[[OHLCV], None]] = None):
        self.symbol = symbol
        self.host = host
        self.port = port
        self.client_id = client_id
        self.on_bar = on_bar
        self.buffer = DataBuffer()
        self.ib = IB()
        self._contract = None
        self._running = False
        self._current_bar: Optional[dict] = None

    def connect(self) -> bool:
        """Connect to IBKR Gateway"""
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            # Get front month contract
            base = Future(self.symbol, exchange='CME')
            contracts = self.ib.reqContractDetails(base)
            if contracts:
                contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
                self._contract = contracts[0].contract
                return True
            return False
        except Exception as e:
            print(f"[{self.symbol}] Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from IBKR"""
        self._running = False
        if self.ib.isConnected():
            self.ib.disconnect()

    def fetch_historical(self, duration: str = '7 D', bar_size: str = '1 hour') -> pd.DataFrame:
        """Fetch historical bars"""
        if not self._contract:
            return pd.DataFrame()

        bars = self.ib.reqHistoricalData(
            self._contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )

        if not bars:
            return pd.DataFrame()

        return pd.DataFrame([
            {'timestamp': b.date.replace(tzinfo=timezone.utc) if b.date.tzinfo is None else b.date,
             'open': b.open, 'high': b.high, 'low': b.low,
             'close': b.close, 'volume': b.volume}
            for b in bars
        ])

    def fetch_missing(self, since: datetime, bar_size: str = '1 min') -> pd.DataFrame:
        """Fetch bars from a given timestamp up to now."""
        if not self._contract:
            return pd.DataFrame()
        now = datetime.now(timezone.utc)
        if since is None or since >= now:
            return pd.DataFrame()

        delta = now - since
        minutes = int(delta.total_seconds() // 60)
        if minutes <= 0:
            return pd.DataFrame()

        # IBKR durationStr: cap to 30 days to avoid huge requests
        days = max(1, min(30, (minutes // (24 * 60)) + 1))
        duration = f"{days} D"

        bars = self.ib.reqHistoricalData(
            self._contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        if not bars:
            return pd.DataFrame()

        df = pd.DataFrame([
            {'timestamp': b.date.replace(tzinfo=timezone.utc) if b.date.tzinfo is None else b.date,
             'open': b.open, 'high': b.high, 'low': b.low,
             'close': b.close, 'volume': b.volume}
            for b in bars
        ])
        return df[df['timestamp'] > since]

    def _on_realtime_bar(self, bars, has_new_bar):
        """Callback for real-time 5-sec bars - aggregate to 1-min"""
        if not has_new_bar:
            return

        bar = bars[-1]
        bar_time = bar.time.replace(second=0, microsecond=0)

        if self._current_bar is None or self._current_bar['timestamp'] != bar_time:
            # New minute - save previous and start new
            if self._current_bar is not None:
                ohlcv = OHLCV(**self._current_bar)
                self.buffer.add(ohlcv)
                if self.on_bar:
                    self.on_bar(ohlcv)

            self._current_bar = {
                'timestamp': bar_time,
                'open': bar.open_,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            }
        else:
            # Same minute - update OHLC
            self._current_bar['high'] = max(self._current_bar['high'], bar.high)
            self._current_bar['low'] = min(self._current_bar['low'], bar.low)
            self._current_bar['close'] = bar.close
            self._current_bar['volume'] += bar.volume

    def stream(self):
        """Stream real-time 5-sec bars (aggregated to 1-min)"""
        if not self._contract:
            print(f"[{self.symbol}] No contract - call connect() first")
            return

        self._running = True
        self.ib.reqMarketDataType(3)  # Delayed data

        realtime_bars = self.ib.reqRealTimeBars(
            self._contract, 5, 'TRADES', False
        )
        realtime_bars.updateEvent += self._on_realtime_bar

        while self._running:
            self.ib.sleep(1)

        self.ib.cancelRealTimeBars(realtime_bars)

    @property
    def contract_symbol(self) -> str:
        return self._contract.localSymbol if self._contract else self.symbol


# Quick test
if __name__ == '__main__':
    import asyncio

    async def test_binance():
        print("Testing Binance...")
        client = BinanceClient()

        # Test historical
        df = await client.fetch_historical('1h', 24)
        print(f"Historical: {len(df)} bars")
        print(df.tail(3))

        # Test streaming (5 seconds)
        print("\nStreaming for 5 seconds...")
        task = asyncio.create_task(client.stream())
        await asyncio.sleep(5)
        client.stop()
        print(f"Buffer: {len(client.buffer.bars)} bars")

    asyncio.run(test_binance())

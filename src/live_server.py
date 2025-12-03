"""
Live WebSocket Server for Real-Time Dashboard
Streams ES + BTC prices to browser via WebSocket
WITH correlation analysis and lead/lag detection
"""

import asyncio
import os
from datetime import datetime, timezone, timedelta
import math
from pathlib import Path
import time
from aiohttp import web
import aiohttp
import pandas as pd

# Use orjson for 10x faster JSON serialization
try:
    import orjson
    def json_dumps(data):
        # OPT_SERIALIZE_NUMPY handles numpy.float64, numpy.int64, etc.
        return orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY).decode('utf-8')
    def json_loads(data):
        return orjson.loads(data)
    print("[PERF] Using orjson (10x faster) with numpy support")
except ImportError:
    import json
    def json_dumps(data):
        return json.dumps(data)
    def json_loads(data):
        return json.loads(data)
    print("[PERF] Using stdlib json (slower)")

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from data_sources import BinanceClient, IBKRClient, OHLCV, DataBuffer
from analysis import calculate_correlation, MultiTimeframeAnalysis, CorrelationResult


class LiveDashboardServer:
    """WebSocket server that streams live data to browser with correlation analysis"""

    def __init__(self, host='127.0.0.1', port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.running = False

        # Data sources
        self.ibkr = IBKRClient(symbol='ES', on_bar=self._on_es_bar)
        self.binance = BinanceClient(on_bar=self._on_btc_bar)

        # Historical data cache (for charts)
        self.es_historical = []
        self.btc_historical = []
        self.es_backfill = []
        self.btc_backfill = []

        # Synchronized bar buffers for correlation (aligned by timestamp)
        self.es_bar_buffer = []  # List of {timestamp, ohlcv}
        self.btc_bar_buffer = []
        self.MAX_BUFFER_SIZE = 1500  # ~25 hours of 1-min data

        # Latest prices for live tick updates (separate from bar data)
        self.latest_es_tick = None
        self.latest_btc_tick = None

        # Latest completed bars
        self.latest_es_bar = None
        self.latest_btc_bar = None

        # Tick streaming
        self.btc_ws = None

        # Correlation results cache
        self.latest_correlation = None

        # Tick batching for high-frequency updates
        self._tick_queue = []
        self._tick_flush_task = None

    @staticmethod
    def _is_valid_price(value) -> bool:
        return isinstance(value, (int, float)) and math.isfinite(value)

    def _bar_to_dict(self, bar: OHLCV) -> dict | None:
        """Safely convert bar to payload or None if invalid"""
        if not bar:
            return None
        if not all([
            self._is_valid_price(bar.open),
            self._is_valid_price(bar.high),
            self._is_valid_price(bar.low),
            self._is_valid_price(bar.close),
            self._is_valid_price(bar.volume),
        ]):
            return None
        return {
            'time': int(self._align_timestamp(bar.timestamp).timestamp()),
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': float(bar.volume),
        }

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove non-finite rows before serialization"""
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        numeric_cols = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
        for col in numeric_cols:
            df = df[pd.to_numeric(df[col], errors='coerce').apply(math.isfinite)]
        df = df.dropna(subset=['timestamp'] + numeric_cols)
        return df

    async def _broadcast(self, data: dict):
        """Send data to all connected clients (optimized)"""
        if not self.clients:
            return
        # Use orjson for faster serialization
        message = json_dumps(data)
        # Send to all clients, ignore errors
        for client in list(self.clients):
            try:
                await client.send_str(message)
            except:
                pass  # Client disconnected

    def _queue_tick(self, symbol: str, price: float, ts: int):
        """Queue a tick for batched broadcast (reduces overhead)"""
        if not self._is_valid_price(price):
            return
        self._tick_queue.append({'s': symbol, 'p': price, 't': ts})

        # Start flush task if not running
        if self._tick_flush_task is None or self._tick_flush_task.done():
            self._tick_flush_task = asyncio.create_task(self._flush_ticks())

    async def _flush_ticks(self):
        """Flush queued ticks every 8ms (~120fps) for smooth updates"""
        await asyncio.sleep(0.008)  # Batch window: 8ms
        if self._tick_queue:
            ticks = self._tick_queue
            self._tick_queue = []
            await self._broadcast({'type': 'ticks', 'data': ticks})

    def _align_timestamp(self, ts: datetime) -> datetime:
        """Align timestamp to start of minute in UTC"""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.replace(second=0, microsecond=0)

    def _on_es_bar(self, bar: OHLCV):
        """Callback when new ES bar completes"""
        payload = self._bar_to_dict(bar)
        if payload is None:
            print("[ES] Skipping invalid bar")
            return
        self.latest_es_bar = bar
        aligned_ts = self._align_timestamp(bar.timestamp)

        # Store in synchronized buffer
        self.es_bar_buffer.append({
            'timestamp': aligned_ts,
            'open': bar.open, 'high': bar.high,
            'low': bar.low, 'close': bar.close,
            'volume': bar.volume
        })
        if len(self.es_bar_buffer) > self.MAX_BUFFER_SIZE:
            self.es_bar_buffer.pop(0)

        # Broadcast bar update
        asyncio.create_task(self._broadcast({
            'type': 'bar',
            'symbol': 'ES',
            'data': payload
        }))
        print(f"[ES] {bar.timestamp.strftime('%H:%M:%S')} Close: {bar.close:.2f}")

        # Trigger correlation calculation after each bar
        asyncio.create_task(self._calculate_and_broadcast_correlation())

    def _on_btc_bar(self, bar: OHLCV):
        """Callback when new BTC bar completes"""
        payload = self._bar_to_dict(bar)
        if payload is None:
            print("[BTC] Skipping invalid bar")
            return
        self.latest_btc_bar = bar
        aligned_ts = self._align_timestamp(bar.timestamp)

        # Store in synchronized buffer
        self.btc_bar_buffer.append({
            'timestamp': aligned_ts,
            'open': bar.open, 'high': bar.high,
            'low': bar.low, 'close': bar.close,
            'volume': bar.volume
        })
        if len(self.btc_bar_buffer) > self.MAX_BUFFER_SIZE:
            self.btc_bar_buffer.pop(0)

        # Broadcast bar update
        asyncio.create_task(self._broadcast({
            'type': 'bar',
            'symbol': 'BTC',
            'data': payload
        }))
        print(f"[BTC] {bar.timestamp.strftime('%H:%M:%S')} Close: {bar.close:.2f}")

        # Trigger correlation calculation after each bar
        asyncio.create_task(self._calculate_and_broadcast_correlation())

    async def _calculate_and_broadcast_correlation(self):
        """Calculate multi-timeframe correlation and broadcast to clients"""
        try:
            # Need at least 20 bars to calculate meaningful correlation
            if len(self.es_bar_buffer) < 20 or len(self.btc_bar_buffer) < 20:
                return

            # Convert to DataFrames
            es_df = pd.DataFrame(self.es_bar_buffer)
            btc_df = pd.DataFrame(self.btc_bar_buffer)

            # Run multi-timeframe analysis
            analyzer = MultiTimeframeAnalysis(es_df, btc_df)
            results = analyzer.analyze_all()

            self.latest_correlation = results

            # Broadcast to all clients
            await self._broadcast({
                'type': 'correlation',
                'data': results
            })

            # Log lead/lag info
            if '1m' in results and results['1m']['lead_lag'] != 0:
                leader = results['1m']['leader']
                lag = abs(results['1m']['lead_lag'])
                corr = results['1m']['correlation']
                print(f"[CORR] {leader} leads by {lag} bar(s), r={corr:.3f}")

        except Exception as e:
            print(f"[CORR] Error calculating correlation: {e}")

    async def _fetch_backfill(self):
        """Fetch last 24h of 1-min data for both assets"""
        print("[INIT] Fetching backfill data (last 24 hours)...")

        # BTC backfill - last 24 hours of 1-min bars (1440 bars)
        try:
            btc_df = await self.binance.fetch_historical('1m', 1440)
            btc_df = self._clean_dataframe(btc_df)
            if not btc_df.empty:
                self.btc_backfill = [
                    {'time': int(row['timestamp'].timestamp()),
                     'open': row['open'], 'high': row['high'],
                     'low': row['low'], 'close': row['close'],
                     'volume': row['volume']}
                    for _, row in btc_df.iterrows()
                ]
                # Also populate the synchronized buffer
                for _, row in btc_df.iterrows():
                    aligned_ts = self._align_timestamp(row['timestamp'])
                    self.btc_bar_buffer.append({
                        'timestamp': aligned_ts,
                        'open': row['open'], 'high': row['high'],
                        'low': row['low'], 'close': row['close'],
                        'volume': row['volume']
                    })
                print(f"[BTC] Backfill: {len(self.btc_backfill)} bars")
        except Exception as e:
            print(f"[BTC] Backfill error: {e}")

        # ES backfill - last 24 hours (86400 seconds)
        try:
            es_df = self.ibkr.fetch_historical('3 D', '1 min')  # 3 trading days of 1-min bars
            es_df = self._clean_dataframe(es_df)
            if es_df is not None and not es_df.empty:
                self.es_backfill = [
                    {'time': int(row['timestamp'].timestamp()),
                     'open': row['open'], 'high': row['high'],
                     'low': row['low'], 'close': row['close'],
                     'volume': row['volume']}
                    for _, row in es_df.iterrows()
                ]
                # Also populate the synchronized buffer
                for _, row in es_df.iterrows():
                    aligned_ts = self._align_timestamp(row['timestamp'])
                    self.es_bar_buffer.append({
                        'timestamp': aligned_ts,
                        'open': row['open'], 'high': row['high'],
                        'low': row['low'], 'close': row['close'],
                        'volume': row['volume']
                    })
                print(f"[ES] Backfill: {len(self.es_backfill)} bars")
        except Exception as e:
            print(f"[ES] Backfill error: {e}")

        # Historical 7-day hourly
        print("[INIT] Fetching historical data (7 days)...")
        try:
            btc_hist = await self.binance.fetch_historical('1h', 168)
            btc_hist = self._clean_dataframe(btc_hist)
            if not btc_hist.empty:
                self.btc_historical = [
                    {'time': int(row['timestamp'].timestamp()),
                     'open': row['open'], 'high': row['high'],
                     'low': row['low'], 'close': row['close'],
                     'volume': row['volume']}
                    for _, row in btc_hist.iterrows()
                ]
                print(f"[BTC] Historical: {len(self.btc_historical)} bars")
        except Exception as e:
            print(f"[BTC] Historical error: {e}")

        # Heal any gaps since the last bar (startup/reconnect)
        await self._heal_gaps()

    async def _heal_gaps(self):
        """Fetch missing bars from last known timestamp to now for BTC and ES."""
        try:
            now_ts = datetime.now(timezone.utc)

            # BTC gaps (1m)
            if self.btc_backfill:
                last_btc_ts = datetime.fromtimestamp(self.btc_backfill[-1]['time'], tz=timezone.utc)
                missing_min = int((now_ts - last_btc_ts).total_seconds() // 60)
                if missing_min > 1:
                    limit = min(missing_min, 1440)
                    print(f"[GAP][BTC] Missing {missing_min} min; fetching {limit} bars")
                    btc_df = await self.binance.fetch_historical('1m', limit)
                    btc_df = self._clean_dataframe(btc_df)
                    if not btc_df.empty:
                        btc_df = btc_df[btc_df['timestamp'] > last_btc_ts]
                        new_bars = [
                            {'time': int(row['timestamp'].timestamp()),
                             'open': row['open'], 'high': row['high'],
                             'low': row['low'], 'close': row['close'],
                             'volume': row['volume']}
                            for _, row in btc_df.iterrows()
                        ]
                        if new_bars:
                            self.btc_backfill.extend(new_bars)
                            for bar in new_bars:
                                aligned_ts = self._align_timestamp(datetime.fromtimestamp(bar['time'], tz=timezone.utc))
                                self.btc_bar_buffer.append({
                                    'timestamp': aligned_ts,
                                    'open': bar['open'], 'high': bar['high'],
                                    'low': bar['low'], 'close': bar['close'],
                                    'volume': bar['volume']
                                })
                            print(f"[GAP][BTC] Filled {len(new_bars)} missing bars")

            # ES gaps (1m)
            if self.es_backfill:
                last_es_ts = datetime.fromtimestamp(self.es_backfill[-1]['time'], tz=timezone.utc)
                missing_min = int((now_ts - last_es_ts).total_seconds() // 60)
                if missing_min > 1:
                    print(f"[GAP][ES] Missing {missing_min} min; fetching via IBKR")
                    es_df = self.ibkr.fetch_missing(last_es_ts, '1 min')
                    es_df = self._clean_dataframe(es_df)
                    if not es_df.empty:
                        es_df = es_df[es_df['timestamp'] > last_es_ts]
                        new_bars = [
                            {'time': int(self._align_timestamp(row['timestamp']).timestamp()),
                             'open': row['open'], 'high': row['high'],
                             'low': row['low'], 'close': row['close'],
                             'volume': row['volume']}
                            for _, row in es_df.iterrows()
                        ]
                        if new_bars:
                            self.es_backfill.extend(new_bars)
                            for bar in new_bars:
                                aligned_ts = datetime.fromtimestamp(bar['time'], tz=timezone.utc)
                                self.es_bar_buffer.append({
                                    'timestamp': aligned_ts,
                                    'open': bar['open'], 'high': bar['high'],
                                    'low': bar['low'], 'close': bar['close'],
                                    'volume': bar['volume']
                                })
                            print(f"[GAP][ES] Filled {len(new_bars)} missing bars")

        except Exception as e:
            print(f"[GAP] Error healing gaps: {e}")

        try:
            es_hist = self.ibkr.fetch_historical('7 D', '1 hour')
            es_hist = self._clean_dataframe(es_hist)
            if es_hist is not None and not es_hist.empty:
                self.es_historical = [
                    {'time': int(row['timestamp'].timestamp()),
                     'open': row['open'], 'high': row['high'],
                     'low': row['low'], 'close': row['close'],
                     'volume': row['volume']}
                    for _, row in es_hist.iterrows()
                ]
                print(f"[ES] Historical: {len(self.es_historical)} bars")
        except Exception as e:
            print(f"[ES] Historical error: {e}")

        # Calculate initial correlation from backfill data
        await self._calculate_and_broadcast_correlation()

    async def websocket_handler(self, request):
        """Handle WebSocket connections"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.clients.add(ws)
        print(f"[WS] Client connected ({len(self.clients)} total)")

        # Send initial data
        init_data = {
            'type': 'init',
            'es_backfill': self.es_backfill,
            'btc_backfill': self.btc_backfill,
            'es_historical': self.es_historical,
            'btc_historical': self.btc_historical,
            'es_contract': self.ibkr.contract_symbol
        }

        # Include latest correlation if available
        if self.latest_correlation:
            init_data['correlation'] = self.latest_correlation

        await ws.send_json(init_data)

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # Handle client messages if needed
                    pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"[WS] Error: {ws.exception()}")
        finally:
            self.clients.discard(ws)
            print(f"[WS] Client disconnected ({len(self.clients)} total)")

        return ws

    async def index_handler(self, request):
        """Serve the dashboard HTML"""
        html_path = Path(__file__).parent.parent / 'output' / 'live_dashboard.html'
        if html_path.exists():
            return web.FileResponse(html_path)
        return web.Response(text="Dashboard not found", status=404)

    async def micro_handler(self, request):
        """Serve the micro-view dashboard HTML"""
        html_path = Path(__file__).parent.parent / 'output' / 'micro_dashboard.html'
        if html_path.exists():
            return web.FileResponse(html_path)
        return web.Response(text="Micro dashboard not found", status=404)

    def _run_ibkr_stream(self):
        """Run IBKR stream in thread"""
        self.ibkr.stream()

    async def _stream_btc_ticks(self):
        """Stream BTC trades for real-time price updates (batched for efficiency)"""
        import websockets
        url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
        last_price = None

        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    print("[BTC] Connected to Binance WebSocket (push)")
                    async for msg in ws:
                        if not self.running:
                            break
                        data = json_loads(msg)
                        price = float(data['p'])
                        ts = int(data['T'])  # Trade timestamp from Binance

                        # Only queue if price changed (reduces noise)
                        if self._is_valid_price(price) and price != last_price:
                            self.latest_btc_tick = price
                            self._queue_tick('BTC', price, ts)
                            last_price = price
            except Exception as e:
                if self.running:
                    print(f"[BTC TICK] Error: {e}, reconnecting...")
                    await asyncio.sleep(1)

    async def _stream_es_ticks(self):
        """Stream ES ticks from IBKR market data using TRUE PUSH events (batched)"""
        last_price = [None]  # Use list to allow modification in closure

        # Subscribe to market data
        if not self.ibkr._contract:
            return

        self.ibkr.ib.reqMarketDataType(3)  # Delayed if no live subscription
        ticker = self.ibkr.ib.reqMktData(self.ibkr._contract, '', False, False)

        # TRUE PUSH: Event callback when ticker updates
        def on_ticker_update(t):
            if not self.running:
                return

            # Get current price - prefer last trade, fallback to bid/ask mid
            price = t.last if t.last == t.last else None
            if price is None:
                if t.bid == t.bid and t.ask == t.ask and t.bid > 0 and t.ask > 0:
                    price = (t.bid + t.ask) / 2
                elif t.close == t.close:
                    price = t.close

            # Only queue if price changed
            if price is not None and self._is_valid_price(price) and price != last_price[0]:
                self.latest_es_tick = price
                ts = int(asyncio.get_event_loop().time() * 1000)
                self._queue_tick('ES', price, ts)
                last_price[0] = price

        # Connect the push event
        ticker.updateEvent += on_ticker_update
        print("[ES] Connected to IBKR push event (ticker.updateEvent)")

        # Keep alive while running
        while self.running:
            await asyncio.sleep(1)  # Just keep the coroutine alive

        # Cleanup
        ticker.updateEvent -= on_ticker_update
        self.ibkr.ib.cancelMktData(self.ibkr._contract)

    async def _periodic_correlation_update(self):
        """Periodically recalculate and broadcast correlation (every 30 seconds)"""
        while self.running:
            await asyncio.sleep(30)
            await self._calculate_and_broadcast_correlation()

    async def run(self):
        """Start the server"""
        print("=" * 60)
        print("ES/BTC LIVE CORRELATION DASHBOARD")
        print("=" * 60)

        # Connect to IBKR
        print("\n[INIT] Connecting to IBKR Gateway...")
        if not self.ibkr.connect():
            print("[FAIL] Could not connect to IBKR. Is Gateway running?")
            return

        print(f"[OK] Connected - Contract: {self.ibkr.contract_symbol}")

        # Fetch backfill data
        await self._fetch_backfill()

        # Generate the live dashboard HTML
        self._generate_live_html()
        # Generate the micro view (realtime + overlay, no historical panes)
        self._generate_micro_html()

        # Setup web server
        app = web.Application()
        app.router.add_get('/', self.index_handler)
        app.router.add_get('/micro', self.micro_handler)
        app.router.add_get('/ws', self.websocket_handler)
        app.router.add_get('/reload-token', self.reload_token_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        print(f"\n[SERVER] Dashboard: http://{self.host}:{self.port}")
        print("[SERVER] Press Ctrl+C to stop\n")

        # Start data streams
        self.running = True

        # Binance WebSocket for candles
        binance_task = asyncio.create_task(self.binance.stream())

        # BTC tick stream for live prices (every 100ms throttled)
        btc_tick_task = asyncio.create_task(self._stream_btc_ticks())

        # IBKR in thread (for candles)
        import threading
        ibkr_thread = threading.Thread(target=self._run_ibkr_stream, daemon=True)
        ibkr_thread.start()

        # ES tick stream (real-time last price)
        es_tick_task = asyncio.create_task(self._stream_es_ticks())

        # Periodic correlation update
        corr_task = asyncio.create_task(self._periodic_correlation_update())

        # Open browser
        import webbrowser
        webbrowser.open(f'http://{self.host}:{self.port}')

        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n[STOP] Shutting down...")
        finally:
            self.running = False
            self.binance.stop()
            self.ibkr.disconnect()
            binance_task.cancel()
            btc_tick_task.cancel()
            es_tick_task.cancel()
            corr_task.cancel()
            await runner.cleanup()
            print("[OK] Shutdown complete")

    def _reload_token_path(self) -> Path:
        return Path(__file__).parent.parent / 'output' / 'reload.token'

    def _load_reload_token(self) -> str:
        try:
            return self._reload_token_path().read_text(encoding='utf-8').strip()
        except Exception:
            return ''

    async def reload_token_handler(self, request):
        """Expose a tiny reload token endpoint for dev auto-refresh."""
        token = self._load_reload_token()
        return web.Response(text=token or '', headers={'Cache-Control': 'no-store'})

    def _generate_live_html(self):
        """Generate the live WebSocket-powered dashboard with correlation analysis"""
        reload_token = self._load_reload_token() or str(int(time.time()))
        html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ES/BTC Live Correlation Dashboard</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0f;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .header {
            background: linear-gradient(180deg, #1a1a2e 0%, #0a0a0f 100%);
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #2a2a3e;
        }
        .header h1 { font-size: 18px; font-weight: 500; color: #fff; }
        .status { display: flex; align-items: center; gap: 10px; }
        .status-dot {
            width: 8px; height: 8px; border-radius: 50%;
            background: #ef5350;
            animation: pulse 1s infinite;
        }
        .status-dot.connected { background: #00C853; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .latency { font-size: 11px; color: #787b86; margin-left: 10px; }
        .latency span { color: #00C853; font-family: 'SF Mono', monospace; }

        /* Price boxes with % change */
        .prices {
            display: flex;
            justify-content: center;
            gap: 40px;
            padding: 15px;
            background: #12121a;
        }
        .price-box {
            text-align: center;
            padding: 10px 20px;
            border-radius: 8px;
            min-width: 180px;
        }
        .price-box.es { border-left: 3px solid #26a69a; }
        .price-box.btc { border-left: 3px solid #42A5F5; }
        .price-label { font-size: 12px; color: #787b86; margin-bottom: 4px; }
        .price-value {
            font-size: 28px;
            font-weight: 600;
            font-family: 'SF Mono', monospace;
            transition: color 0.2s;
        }
        .price-value.up { color: #00C853; }
        .price-value.down { color: #ef5350; }
        .price-pct {
            font-size: 14px;
            font-weight: 500;
            margin-top: 4px;
            font-family: 'SF Mono', monospace;
        }
        .price-pct.up { color: #00C853; }
        .price-pct.down { color: #ef5350; }

        /* Trading Signal Box */
        .trading-signal {
            background: linear-gradient(180deg, #1a1a2e 0%, #12121a 100%);
            padding: 12px 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 30px;
            border-bottom: 1px solid #2a2a3e;
        }
        .signal-box {
            background: #0f0f14;
            border-radius: 8px;
            padding: 12px 20px;
            text-align: center;
            min-width: 200px;
        }
        .signal-box.highlight {
            border: 1px solid #00C853;
            box-shadow: 0 0 10px rgba(0,200,83,0.2);
        }
        .signal-label { font-size: 10px; color: #787b86; text-transform: uppercase; margin-bottom: 4px; }
        .signal-value { font-size: 18px; font-weight: 600; }
        .signal-detail { font-size: 11px; color: #787b86; margin-top: 4px; }

        .correlation-bar {
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 12px;
            background: #0f0f14;
            border-bottom: 1px solid #2a2a3e;
            flex-wrap: wrap;
        }
        .corr-item {
            text-align: center;
            min-width: 60px;
            padding: 6px 12px;
            border-radius: 4px;
            background: #12121a;
        }
        .corr-label { font-size: 10px; color: #787b86; text-transform: uppercase; }
        .corr-value { font-size: 18px; font-weight: 600; margin-top: 2px; }
        .lead-lag-box {
            background: #1a1a2e;
            padding: 10px 20px;
            border-radius: 8px;
            text-align: center;
            min-width: 160px;
        }
        .lead-lag-label { font-size: 10px; color: #787b86; text-transform: uppercase; }
        .lead-lag-value { font-size: 18px; font-weight: 600; margin-top: 4px; }
        .lead-lag-detail { font-size: 11px; color: #787b86; margin-top: 2px; }
        .section-title {
            padding: 12px 20px 8px;
            font-size: 12px;
            color: #787b86;
            text-transform: uppercase;
            letter-spacing: 1px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .section-title .toggle {
            font-size: 10px;
            padding: 4px 8px;
            background: #1a1a2e;
            border: 1px solid #2a2a3e;
            border-radius: 4px;
            color: #787b86;
            cursor: pointer;
        }
        .section-title .toggle:hover { background: #2a2a3e; }
        .section-title .toggle.active { background: #26a69a; color: #fff; border-color: #26a69a; }
        .charts-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1px;
            background: #2a2a3e;
        }
        .chart-wrapper {
            background: #0a0a0f;
            position: relative;
            height: 280px;
        }
        .chart-label {
            position: absolute;
            top: 8px;
            left: 12px;
            font-size: 11px;
            font-weight: 600;
            padding: 4px 8px;
            border-radius: 4px;
            z-index: 10;
        }
        .chart-label.es { background: rgba(38,166,154,0.2); color: #26a69a; }
        .chart-label.btc { background: rgba(66,165,245,0.2); color: #42A5F5; }
        .chart-wrapper.historical { height: 240px; }
        .chart-wrapper.correlation { height: 350px; }
        .chart-wrapper.full-width { grid-column: span 2; height: 300px; }
        .correlation-legend {
            position: absolute;
            top: 10px;
            left: 15px;
            z-index: 10;
            background: rgba(10, 10, 15, 0.9);
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 11px;
        }
        .correlation-legend .item {
            display: flex;
            align-items: center;
            gap: 6px;
            margin: 4px 0;
        }
        .correlation-legend .dot {
            width: 10px;
            height: 3px;
            border-radius: 2px;
        }
        .legend {
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 10px;
            font-size: 11px;
            color: #787b86;
        }
        .legend-item { display: flex; align-items: center; gap: 5px; }
        .legend-dot { width: 8px; height: 8px; border-radius: 50%; }

        /* COMPACT HEADER - All in one row */
        .compact-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 15px;
            background: linear-gradient(180deg, #1a1a2e 0%, #12121a 100%);
            border-bottom: 1px solid #2a2a3e;
            gap: 20px;
        }
        .price-section {
            display: flex;
            gap: 25px;
        }
        .price-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 4px 12px;
            border-radius: 4px;
            background: rgba(0,0,0,0.3);
        }
        .price-item.es { border-left: 3px solid #26a69a; }
        .price-item.btc { border-left: 3px solid #42A5F5; }
        .price-item .label { font-size: 11px; color: #787b86; min-width: 50px; }
        .price-item .price {
            font-size: 22px;
            font-weight: 600;
            font-family: 'SF Mono', 'Consolas', monospace;
            min-width: 100px;
            transition: color 0.15s;
        }
        .price-item .price.up { color: #00C853; }
        .price-item .price.down { color: #ef5350; }
        .price-item .pct {
            font-size: 13px;
            font-weight: 500;
            font-family: 'SF Mono', monospace;
            min-width: 65px;
        }
        .price-item .pct.up { color: #00C853; }
        .price-item .pct.down { color: #ef5350; }

        .corr-section {
            display: flex;
            gap: 8px;
        }
        .corr-mini {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 4px 10px;
            background: rgba(0,0,0,0.3);
            border-radius: 4px;
            min-width: 45px;
        }
        .corr-mini.highlight {
            background: rgba(0,200,83,0.15);
            border: 1px solid rgba(0,200,83,0.3);
        }
        .corr-mini .tf { font-size: 9px; color: #787b86; text-transform: uppercase; }
        .corr-mini .val { font-size: 16px; font-weight: 600; }

        .signal-section {
            display: flex;
            gap: 15px;
        }
        .signal-item, .lead-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 4px 12px;
            background: rgba(0,0,0,0.3);
            border-radius: 4px;
            min-width: 80px;
        }
        .anchor-toggle {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-left: 10px;
        }
        .anchor-btn {
            font-size: 10px;
            padding: 4px 8px;
            background: rgba(0,0,0,0.3);
            border: 1px solid #2a2a3e;
            color: #787b86;
            border-radius: 4px;
            cursor: pointer;
        }
        .anchor-btn.active {
            background: #26a69a;
            color: #fff;
            border-color: #26a69a;
        }
        .measure-btn {
            font-size: 10px;
            padding: 4px 8px;
            background: rgba(0,0,0,0.3);
            border: 1px solid #2a2a3e;
            color: #787b86;
            border-radius: 4px;
            cursor: pointer;
        }
        .measure-btn.active {
            background: #42A5F5;
            color: #fff;
            border-color: #42A5F5;
        }
        .measure-rect {
            position: absolute;
            background: rgba(66,165,245,0.18);
            border: 1px dashed rgba(66,165,245,0.8);
            pointer-events: none;
            z-index: 100;  /* Higher than chart canvas layers */
        }
        .measure-label {
            position: absolute;
            background: rgba(10,10,15,0.92);
            color: #fff;
            padding: 8px 10px;
            border-radius: 5px;
            font-size: 12px;
            pointer-events: none;
            z-index: 101;  /* Higher than measure-rect */
            border: 1px solid rgba(66,165,245,0.7);
            white-space: nowrap;
            box-shadow: 0 2px 6px rgba(0,0,0,0.5);
        }
        .signal-item.highlight {
            background: rgba(0,200,83,0.15);
            border: 1px solid rgba(0,200,83,0.3);
            animation: glow 1s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { box-shadow: 0 0 5px rgba(0,200,83,0.3); }
            to { box-shadow: 0 0 15px rgba(0,200,83,0.5); }
        }
        .signal-label, .lead-label { font-size: 9px; color: #787b86; text-transform: uppercase; }
        .signal-value { font-size: 14px; font-weight: 600; }
        .lead-value { font-size: 14px; font-weight: 600; }

        .status-section {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 11px;
            color: #787b86;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ef5350;
        }
        .status-dot.connected { background: #00C853; }
        .latency {
            font-family: 'SF Mono', monospace;
            color: #00C853;
            min-width: 45px;
        }
        .latency.slow { color: #FFD600; }
        .latency.very-slow { color: #ef5350; }
        .rate { font-family: 'SF Mono', monospace; }
    </style>
</head>
<body>
    <!-- COMPACT HEADER: All key info in one row -->
    <div class="compact-header">
        <div class="price-section">
            <div class="price-item es">
                <span class="label">ES <span id="es-contract">---</span></span>
                <span class="price" id="es-price">---</span>
                <span class="pct" id="es-pct">--</span>
            </div>
            <div class="price-item btc">
                <span class="label">BTC</span>
                <span class="price" id="btc-price">---</span>
                <span class="pct" id="btc-pct">--</span>
            </div>
        </div>
        <div class="corr-section">
            <div class="corr-mini"><span class="tf">1m</span><span id="corr-1m" class="val">--</span></div>
            <div class="corr-mini"><span class="tf">5m</span><span id="corr-5m" class="val">--</span></div>
            <div class="corr-mini"><span class="tf">15m</span><span id="corr-15m" class="val">--</span></div>
            <div class="corr-mini highlight"><span class="tf">1H</span><span id="corr-1h" class="val">--</span></div>
        </div>
        <div class="signal-section">
            <div class="signal-item" id="signal-box">
                <span class="signal-label">SIGNAL</span>
                <span class="signal-value" id="trading-signal">--</span>
            </div>
            <div class="lead-item">
                <span class="lead-label">LEAD</span>
                <span class="lead-value" id="lead-lag-value">SYNC</span>
            </div>
            <div class="anchor-toggle">
                <button id="anchor-globex" class="anchor-btn active">Globex</button>
                <button id="anchor-cash" class="anchor-btn">Cash</button>
            </div>
            <button id="measure-toggle" class="measure-btn">Measure</button>
        </div>
        <div class="status-section">
            <div class="status-dot" id="status-dot"></div>
            <span class="latency" id="latency-display">--ms</span>
            <span class="rate" id="btc-rate">0</span>/s
        </div>
    </div>

    <div class="section-title">
        <span>Real-Time (1 Min Candles)</span>
    </div>
    <div class="charts-container">
        <div class="chart-wrapper" id="es-realtime">
            <div class="chart-label es">ES Futures</div>
        </div>
        <div class="chart-wrapper" id="btc-realtime">
            <div class="chart-label btc">BTC/USDT</div>
        </div>
    </div>

    <div class="section-title">Historical (7 Days - 1 Hour)</div>
    <div class="charts-container">
        <div class="chart-wrapper historical" id="es-historical">
            <div class="chart-label es">ES Futures</div>
        </div>
        <div class="chart-wrapper historical" id="btc-historical">
            <div class="chart-label btc">BTC/USDT</div>
        </div>
    </div>

    <!-- ALPHA DETECTION SECTION - Coming Soon -->

    <!-- TradingView-Style Overlay Chart -->
    <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #2a2a3e;">
        <div class="section-title">
            <span style="color: #42A5F5; font-size: 16px; font-weight: bold;">CORRELATION OVERLAY</span>
            <span style="color: #787b86; font-size: 12px; margin-left: 10px;">BTC Candles + ES % Change Line</span>
        </div>
        <div style="background: #0a0a0f; position: relative; border: 1px solid #2a2a3e; border-radius: 4px; margin: 10px; overflow: hidden;">
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #1a1a2e; background: #0d0d14;">
                <div style="display: flex; align-items: center; gap: 20px;">
                    <div>
                        <span style="color: #F7931A; font-weight: bold; font-size: 14px;">BTC/USDT</span>
                        <span id="overlay-btc-price" style="color: #e0e0e0; margin-left: 8px; font-size: 14px;">--</span>
                        <span id="overlay-btc-pct" style="margin-left: 4px; font-size: 13px;">--</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <div style="background: #2962FF; width: 20px; height: 3px; border-radius: 2px;"></div>
                        <span style="color: #2962FF; font-weight: bold; font-size: 14px;">ES1!</span>
                        <span id="overlay-es-price" style="color: #e0e0e0; margin-left: 8px; font-size: 14px;">--</span>
                        <span id="overlay-es-pct" style="margin-left: 4px; font-size: 13px;">--</span>
                    </div>
                </div>
                <div style="color: #787b86; font-size: 11px;">Left axis: ES % | Right axis: BTC $</div>
            </div>
            <div style="position: relative; height: 600px;">
                <div class="chart-wrapper" id="overlay-main-chart" style="height: 100%;"></div>
                <!-- Floating ES price label on right side, positioned at ES line Y level -->
                <div id="es-price-label" style="
                    position: absolute;
                    right: 5px;
                    top: 100px;
                    background: #2962FF;
                    color: white;
                    padding: 4px 10px;
                    font-size: 12px;
                    font-weight: bold;
                    border-radius: 3px;
                    z-index: 9999;
                    pointer-events: none;
                    white-space: nowrap;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                    border: 1px solid #4a7fff;
                ">ES: --</div>
            </div>
            <div class="chart-wrapper" id="overlay-volume-chart" style="height: 150px;"></div>
        </div>
    </div>

    <script>
        // Lightweight logging helper (toggle flag while debugging)
        const CHART_DEBUG = false;  // Set true to debug chart errors
        function chartWarn(msg, ctx) {
            if (CHART_DEBUG) {
                console.warn('[CHART]', msg, ctx || {});
            }
        }
        // Throttle helper for high-frequency chart updates
        const _throttleMap = new Map();
        function throttledChartOp(key, delayMs, fn) {
            const now = Date.now();
            const last = _throttleMap.get(key) || 0;
            if (now - last < delayMs) return;
            _throttleMap.set(key, now);
            try { fn(); } catch (e) { chartWarn('throttled op failed', { key, error: e?.message }); }
        }
        // Suppress noisy LWC "Value is null" errors from both window errors and console
        (function() {
            const originalError = console.error;
            console.error = function(...args) {
                const msg = args.join(' ');
                if (msg.includes('Value is null') || msg.includes('lightweight-charts')) return;
                originalError.apply(console, args);
            };
        })();
        window.addEventListener('error', function(e) {
            if (e && e.message && (e.message.includes('Value is null') || e.message.includes('lightweight-charts'))) {
                e.preventDefault();
                e.stopPropagation();
                return true;
            }
        }, true);
        window.addEventListener('unhandledrejection', function(e) {
            if (e.reason && String(e.reason).includes('Value is null')) {
                e.preventDefault();
                return true;
            }
        });
        // Session anchor modes for ES % base
        const ANCHOR_MODES = { GLOBEX: 'globex', CASH: 'cash' };

        // --- Dev live-reload hook (polls reload token and refreshes on change) ---
        const RELOAD_TOKEN = ''' + f"'{reload_token}'" + ''';
        setInterval(async () => {
            try {
                const res = await fetch('/reload-token', { cache: 'no-store' });
                const txt = await res.text();
                if (txt && txt.trim() !== RELOAD_TOKEN) {
                    console.log('[DEV] Reload token changed, refreshing...');
                    window.location.reload();
                }
            } catch (err) {
                // ignore fetch errors (server restarting)
            }
        }, 2000);
        // ------------------------------------------------------------------------

        // Helper: validate range before time scale sync
        function isValidRange(range) {
            return range && range.from != null && range.to != null &&
                   typeof range.from === 'number' && typeof range.to === 'number' &&
                   isFinite(range.from) && isFinite(range.to) && range.from < range.to;
        }

        // Interaction lock to detect wheel / touch / pinch / scroll gestures
        function createInteractionLock(debounceMs = 300) {
            let active = false;
            let timer = null;

            function activate() {
                active = true;
                if (timer) clearTimeout(timer);
                timer = setTimeout(() => { active = false; }, debounceMs);
            }

            ['wheel', 'touchstart', 'touchmove'].forEach(evt => {
                document.addEventListener(evt, activate, { passive: true });
            });

            return () => active;
        }

        // Chart setup with full navigation
        const chartOptions = {
            layout: { background: { type: 'solid', color: '#0a0a0f' }, textColor: '#787b86' },
            grid: { vertLines: { color: '#1a1a2e' }, horzLines: { color: '#1a1a2e' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: '#2a2a3e', scaleMargins: { top: 0.1, bottom: 0.1 } },
            timeScale: {
                borderColor: '#2a2a3e',
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 5,
                minBarSpacing: 3
            },
            handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true }
        };

        // Global interaction guard used by sync logic
        const isUserInteracting = createInteractionLock(400);
        function isAnyInteraction() {
            return isDragging || overlayDragging || isUserInteracting();
        }

        // === Session anchor helpers (ES % base) ===
        const ANCHOR_DEFAULT = ANCHOR_MODES.GLOBEX;
        let esAnchorMode = ANCHOR_DEFAULT;
        let esAnchorTs = null;  // seconds

        function getEtOffsetMs() {
            const now = new Date();
            const utcNow = new Date(now.toLocaleString('en-US', { timeZone: 'UTC' }));
            const etNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
            return utcNow.getTime() - etNow.getTime();  // UTC minus ET
        }

        function computeAnchorTimestamp(mode) {
            const now = new Date();
            const etNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
            const offsetMs = getEtOffsetMs();
            const isCash = mode === ANCHOR_MODES.CASH;
            const hour = isCash ? 9 : 18;
            const minute = isCash ? 30 : 0;
            const anchorEt = new Date(etNow.getFullYear(), etNow.getMonth(), etNow.getDate(), hour, minute, 0, 0);
            let anchorUtcMs = anchorEt.getTime() + offsetMs;
            const nowUtcMs = Date.now();
            if (nowUtcMs < anchorUtcMs) {
                anchorUtcMs -= 24 * 3600 * 1000;  // roll to previous day
            }
            return Math.floor(anchorUtcMs / 1000);
        }

        function findBasePrice(dataArray, anchorSeconds) {
            if (!dataArray || dataArray.length === 0) return null;
            let base = dataArray[0].close;
            if (!anchorSeconds) return base;
            for (const d of dataArray) {
                if (d.time >= anchorSeconds) {
                    base = d.close;
                    break;
                }
            }
            return base;
        }

        // Create charts
        const esRtChart = LightweightCharts.createChart(document.getElementById('es-realtime'),
            { ...chartOptions, width: document.getElementById('es-realtime').offsetWidth, height: 280 });
        const btcRtChart = LightweightCharts.createChart(document.getElementById('btc-realtime'),
            { ...chartOptions, width: document.getElementById('btc-realtime').offsetWidth, height: 280 });
        const esHistChart = LightweightCharts.createChart(document.getElementById('es-historical'),
            { ...chartOptions, width: document.getElementById('es-historical').offsetWidth, height: 240 });
        const btcHistChart = LightweightCharts.createChart(document.getElementById('btc-historical'),
            { ...chartOptions, width: document.getElementById('btc-historical').offsetWidth, height: 240 });

        // Candlestick series - ES (teal/green), BTC (blue - changed from orange!)
        const esRtSeries = esRtChart.addCandlestickSeries({
            upColor: '#26a69a', downColor: '#ef5350',
            borderUpColor: '#26a69a', borderDownColor: '#ef5350',
            wickUpColor: '#26a69a', wickDownColor: '#ef5350'
        });
        const btcRtSeries = btcRtChart.addCandlestickSeries({
            upColor: '#42A5F5', downColor: '#EF5350',
            borderUpColor: '#42A5F5', borderDownColor: '#EF5350',
            wickUpColor: '#42A5F5', wickDownColor: '#EF5350'
        });
        const esHistSeries = esHistChart.addCandlestickSeries({
            upColor: '#26a69a', downColor: '#ef5350',
            borderUpColor: '#26a69a', borderDownColor: '#ef5350',
            wickUpColor: '#26a69a', wickDownColor: '#ef5350'
        });
        const btcHistSeries = btcHistChart.addCandlestickSeries({
            upColor: '#42A5F5', downColor: '#EF5350',
            borderUpColor: '#42A5F5', borderDownColor: '#EF5350',
            wickUpColor: '#42A5F5', wickDownColor: '#EF5350'
        });

        // ========== TradingView-Style Overlay Chart ==========
        const overlayChartEl = document.getElementById('overlay-main-chart');
        const overlayVolChartEl = document.getElementById('overlay-volume-chart');

        const overlayChart = LightweightCharts.createChart(overlayChartEl, {
            ...chartOptions,
            width: overlayChartEl.offsetWidth,
            height: 600,
            rightPriceScale: {
                borderColor: '#2a2a3e',
                scaleMargins: { top: 0.05, bottom: 0.15 },
                visible: true
            },
            leftPriceScale: {
                borderColor: '#2a2a3e',
                scaleMargins: { top: 0.05, bottom: 0.15 },
                visible: true
            }
        });

        // Volume chart MUST have same width as main chart for alignment
        const overlayVolChart = LightweightCharts.createChart(overlayVolChartEl, {
            ...chartOptions,
            width: overlayChartEl.offsetWidth,  // Use MAIN chart's width!
            height: 150,
            rightPriceScale: { visible: true, scaleMargins: { top: 0.1, bottom: 0 } },
            leftPriceScale: { visible: false },
            timeScale: {
                visible: false,
                rightOffset: 5,
                barSpacing: 6,
                minBarSpacing: 3
            }
        });

        // BTC Candlesticks (main series on RIGHT price scale)
        const overlayBtcSeries = overlayChart.addCandlestickSeries({
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderUpColor: '#26a69a',
            borderDownColor: '#ef5350',
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
            priceScaleId: 'right',
            priceFormat: { type: 'price', precision: 2, minMove: 0.01 }
        });

        // ES Line (% change on LEFT price scale) - blue like TradingView
        const overlayEsSeries = overlayChart.addLineSeries({
            color: '#2962FF',
            lineWidth: 2,
            priceScaleId: 'left',
            priceFormat: {
                type: 'custom',
                minMove: 0.001,
                formatter: (price) => price.toFixed(2) + '%'
            },
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 4,
            lastValueVisible: true,  // Show floating label
            priceLineVisible: true,  // Show price line
            priceLineColor: '#2962FF',
            priceLineWidth: 1,
            priceLineStyle: 2  // Dashed
        });

        // Configure left scale for ES % change - more decimal places
        overlayChart.priceScale('left').applyOptions({
            scaleMargins: { top: 0.05, bottom: 0.15 },
            borderColor: '#2962FF',
            autoScale: true,
            mode: 0  // Normal mode
        });

        // BTC Volume histogram - on RIGHT scale for visibility
        const overlayBtcVolSeries = overlayVolChart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'right',
            lastValueVisible: true,
            priceLineVisible: true
        });

        // CRITICAL: Sync overlay chart with volume chart - PIXEL PERFECT alignment!
        // Track drag state for overlay chart (shared with crosshair sync)
        let overlayDragging = false;
        let overlayDragTimer = null;
        let syncingOverlay = false;

        function markOverlayDragging() {
            overlayDragging = true;
            if (overlayDragTimer) clearTimeout(overlayDragTimer);
            overlayDragTimer = setTimeout(() => { overlayDragging = false; }, 400);
        }

        // Track mouse/touch/scroll state on overlay chart containers
        const overlayMainEl = document.getElementById('overlay-main-chart');
        const overlayVolEl = document.getElementById('overlay-volume-chart');
        [overlayMainEl, overlayVolEl].forEach(el => {
            if (el) {
                ['mousedown', 'mouseup', 'mouseleave', 'wheel', 'touchstart', 'touchmove'].forEach(evt => {
                    el.addEventListener(evt, markOverlayDragging, { passive: true });
                });
            }
        });

        function syncVolToMain() {
            // Don't sync during drag - causes errors
            if (syncingOverlay || overlayDragging) return;
            syncingOverlay = true;
            try {
                // Sync visible range
                const range = overlayChart.timeScale().getVisibleLogicalRange();
                if (isValidRange(range)) {
                    overlayVolChart.timeScale().setVisibleLogicalRange(range);
                }
                // Sync scroll position for pixel-perfect alignment
                const scrollPos = overlayChart.timeScale().scrollPosition();
                if (scrollPos != null && isFinite(scrollPos)) {
                    overlayVolChart.timeScale().scrollToPosition(scrollPos, false);
                }
                // Sync bar spacing
                const bs = overlayChart.timeScale().options().barSpacing;
                if (bs && isFinite(bs) && bs > 0) {
                    overlayVolChart.timeScale().applyOptions({ barSpacing: bs });
                }
            } catch(e) {
                // Chart mid-transition - ignore
            }
            syncingOverlay = false;
        }

        // Main chart drives the volume chart - sync on both events (but not during drag)
        overlayChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            if (!syncingOverlay && !overlayDragging) syncVolToMain();
        });
        overlayChart.timeScale().subscribeVisibleTimeRangeChange(() => {
            if (!syncingOverlay && !overlayDragging) syncVolToMain();
        });

        // Store data for overlay
        let overlayBtcData = [];
        let overlayEsData = [];
        let overlayEsBase = null;
        let currentOverlayBtcBar = null;
        let currentOverlayEsBar = null;
        let overlayEsPriceLine = null;
        let overlayResetting = false;  // guard to avoid update/setData races

        // ES price label positioning function
        function updateEsPriceLabel(esPrice, esPctValue) {
            const label = document.getElementById('es-price-label');
            if (!label || esPrice == null || esPctValue == null) return;

            // Update label text with actual ES price
            label.textContent = 'ES: ' + esPrice.toFixed(2);

            // CRITICAL FIX: Only use priceToCoordinate if series has data
            // This prevents "Value is null" errors when chart is not ready
            try {
                // Verify series has data before calling priceToCoordinate
                const hasData = overlayEsData && overlayEsData.length > 0;
                if (hasData && isFinite(esPctValue)) {
                    const y = overlayEsSeries.priceToCoordinate(esPctValue);
                    if (y != null && isFinite(y) && y > 0 && y < 600) {
                        label.style.top = (y - 8) + 'px';  // Center vertically on the line
                    } else {
                        chartWarn('skip price label - offscreen', { esPctValue, y });
                    }
                }
            } catch (e) {
                chartWarn('price label update failed', { error: e?.message });
            }
        }

        // Re-position ES label when chart scales/zooms - use RAF for smooth updates
        // Skip during drag to prevent errors
        let esPriceLabelRaf = null;
        overlayChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            if (overlayDragging) return;  // Don't update during drag
            if (esPriceLabelRaf) cancelAnimationFrame(esPriceLabelRaf);
            esPriceLabelRaf = requestAnimationFrame(() => {
                if (overlayDragging) return;  // Double-check after RAF
                if (esData.length > 0 && overlayEsBase && overlayEsData.length > 0) {
                    const lastEs = esData[esData.length - 1];
                    const esPct = ((lastEs.close - overlayEsBase) / overlayEsBase) * 100;
                    try { updateEsPriceLabel(lastEs.close, esPct); } catch(e) {}
                }
            });
        });

        // Fast tick update for overlay chart (called on each tick)
        // Skip during drag to prevent "Value is null" errors
        function updateOverlayTick(symbol, price) {
            if (overlayDragging || overlayResetting || isAnyInteraction()) return;  // Don't update series during drag/zoom/reset
            try {
                if (price == null || !isFinite(price)) return;

                const now = Math.floor(Date.now() / 1000 / 60) * 60;

                if (symbol === 'BTC') {
                    // Update BTC candle - with visible range guard
                    if (overlayBtcData.length === 0) return;  // Need initial data first
                    if (!currentOverlayBtcBar || currentOverlayBtcBar.time !== now) {
                        const lastClose = btcData.length > 0 ? btcData[btcData.length - 1].close : price;
                        currentOverlayBtcBar = { time: now, open: lastClose, high: price, low: price, close: price };
                    } else {
                        currentOverlayBtcBar.high = Math.max(currentOverlayBtcBar.high, price);
                        currentOverlayBtcBar.low = Math.min(currentOverlayBtcBar.low, price);
                        currentOverlayBtcBar.close = price;
                    }
                    // Only update if chart has valid visible range
                    const visRange = overlayChart.timeScale().getVisibleLogicalRange();
                    if (isValidRange(visRange)) {
                        throttledChartOp('overlay-btc', 50, () => overlayBtcSeries.update(currentOverlayBtcBar));
                    }

                    // Update header
                    const btcPriceEl = document.getElementById('overlay-btc-price');
                    if (btcPriceEl) btcPriceEl.textContent = price.toFixed(2);
                    if (btcData.length > 0) {
                        const firstBtc = btcData[0];
                        const btcPct = ((price - firstBtc.close) / firstBtc.close) * 100;
                        const btcPctEl = document.getElementById('overlay-btc-pct');
                        if (btcPctEl) {
                            btcPctEl.textContent = (btcPct >= 0 ? '+' : '') + btcPct.toFixed(2) + '%';
                            btcPctEl.style.color = btcPct >= 0 ? '#26a69a' : '#ef5350';
                        }
                    }
                } else if (symbol === 'ES') {
                    // Update ES % line - with visible range guard
                    if (overlayEsBase && esData.length > 0 && overlayEsData.length > 0) {
                        const esPct = ((price - overlayEsBase) / overlayEsBase) * 100;
                        if (!isFinite(esPct)) return;

                        if (!currentOverlayEsBar || currentOverlayEsBar.time !== now) {
                            currentOverlayEsBar = { time: now, value: esPct };
                        } else {
                            currentOverlayEsBar.value = esPct;
                        }
                        // Only update if chart has valid visible range
                        const visRange = overlayChart.timeScale().getVisibleLogicalRange();
                        if (isValidRange(visRange)) {
                            throttledChartOp('overlay-es', 50, () => overlayEsSeries.update(currentOverlayEsBar));
                        }

                        // Update header with ES price and %
                        const esPriceEl = document.getElementById('overlay-es-price');
                        if (esPriceEl) esPriceEl.textContent = price.toFixed(2);
                        const esPctEl = document.getElementById('overlay-es-pct');
                        if (esPctEl) {
                            esPctEl.textContent = (esPct >= 0 ? '+' : '') + esPct.toFixed(2) + '%';
                            esPctEl.style.color = esPct >= 0 ? '#26a69a' : '#ef5350';
                        }

                        // Update floating ES price label on right axis
                        updateEsPriceLabel(price, esPct);
                    }
                }
            } catch (e) {
                // Ignore tick update errors
            }
        }

        // Function to update overlay chart (full reset - called on bar completion)
        // Skip during drag to prevent errors
        function updateOverlayChart() {
            if (overlayDragging) return;  // Don't reset data during drag
            // Allow partial rendering: only skip if BOTH datasets are empty
            if (btcData.length === 0 && esData.length === 0) return;

            overlayResetting = true;
            try {
                // BTC overlay (candlesticks + volume) - only if we have BTC data
                if (btcData.length > 0) {
                    overlayBtcData = btcData.slice();
                    try { overlayBtcSeries.setData(overlayBtcData); } catch(e) { chartWarn('overlay btc setData failed', { error: e?.message }); }

                    // Volume with color
                    const volData = btcData.map(d => ({
                        time: d.time,
                        value: d.volume || 0,
                        color: d.close >= d.open ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)'
                    })).filter(d => d.value > 0);
                    try { overlayBtcVolSeries.setData(volData); } catch(e) { chartWarn('overlay vol setData failed', { error: e?.message }); }
                }

                // ES overlay (% line) - only if we have ES data and base price
                if (esData.length > 0) {
                    if (!overlayEsBase) {
                        overlayEsBase = esBasePrice ?? esData[0].close;
                    }
                    if (overlayEsBase) {
                        overlayEsData = esData.map(d => ({
                            time: d.time,
                            value: ((d.close - overlayEsBase) / overlayEsBase) * 100
                        }));
                        try { overlayEsSeries.setData(overlayEsData); } catch(e) { chartWarn('overlay es setData failed', { error: e?.message }); }
                    }
                }

                // Sync time scales - volume follows main chart EXACTLY
                if (!overlayDragging) {
                    overlayChart.timeScale().fitContent();
                    // Force perfect sync after a brief delay for rendering
                    setTimeout(() => { if (!overlayDragging) syncVolToMain(); }, 50);
                    setTimeout(() => { if (!overlayDragging) syncVolToMain(); }, 200);
                }
            } catch(e) {
                // Chart mid-transition - ignore
            } finally {
                setTimeout(() => { overlayResetting = false; }, 100);  // leave guard up briefly to avoid async render race
            }

            // Update header values
            if (btcData.length > 0) {
                const lastBtc = btcData[btcData.length - 1];
                const firstBtc = btcData[0];
                const btcPct = ((lastBtc.close - firstBtc.close) / firstBtc.close) * 100;

                const btcPriceEl = document.getElementById('overlay-btc-price');
                const btcPctEl = document.getElementById('overlay-btc-pct');
                if (btcPriceEl) btcPriceEl.textContent = lastBtc.close.toFixed(2);
                if (btcPctEl) {
                    btcPctEl.textContent = (btcPct >= 0 ? '+' : '') + btcPct.toFixed(2) + '%';
                    btcPctEl.style.color = btcPct >= 0 ? '#26a69a' : '#ef5350';
                }
            }

            if (esData.length > 0 && overlayEsBase) {
                const lastEs = esData[esData.length - 1];
                const esPct = ((lastEs.close - overlayEsBase) / overlayEsBase) * 100;

                // Show ES actual price
                const esPriceEl = document.getElementById('overlay-es-price');
                if (esPriceEl) esPriceEl.textContent = lastEs.close.toFixed(2);

                // Show ES % change
                const esPctEl = document.getElementById('overlay-es-pct');
                if (esPctEl) {
                    esPctEl.textContent = (esPct >= 0 ? '+' : '') + esPct.toFixed(2) + '%';
                    esPctEl.style.color = esPct >= 0 ? '#26a69a' : '#ef5350';
                }

                // Update floating ES price label on right axis
                try { updateEsPriceLabel(lastEs.close, esPct); } catch(e) {}
            }
        }
        // ========== END: TradingView-Style Overlay Chart ==========

        // Charts are INDEPENDENT - each can be dragged/zoomed separately
        // Only crosshairs are synced (below) for visual comparison

        // Measurement placeholder (legacy tooltip removed); keep a safe clear hook
        function resetMeasurement() {
            try { clearAllMeasurements(); } catch (e) { /* ignore */ }
        }

        // Sync crosshairs between paired charts
        // Track if user is dragging/zooming (don't sync during interaction)
        let isDragging = false;
        let dragTimer = null;
        function markDragging() {
            isDragging = true;
            if (dragTimer) clearTimeout(dragTimer);
            dragTimer = setTimeout(() => { isDragging = false; }, 400);
        }
        // NOTE: mousedown/mouseup removed - they block measurement clicks!
        // Only wheel/touch events should trigger drag detection
        ['wheel', 'touchstart', 'touchmove'].forEach(evt => {
            document.addEventListener(evt, markDragging, { passive: true });
        });

        // Find nearest timestamp in data array (binary search)
        // This is critical because ES and BTC have different trading hours
        function findNearestTime(dataArray, targetTime) {
            if (!dataArray || dataArray.length === 0) return null;

            let left = 0;
            let right = dataArray.length - 1;

            // Binary search
            while (left < right) {
                const mid = Math.floor((left + right) / 2);
                if (dataArray[mid].time < targetTime) {
                    left = mid + 1;
                } else {
                    right = mid;
                }
            }

            // Bounds check: if left exceeds array, return last element
            if (left >= dataArray.length) {
                return dataArray[dataArray.length - 1];
            }

            // Check if left or left-1 is closer
            if (left > 0) {
                const diffLeft = Math.abs(dataArray[left].time - targetTime);
                const diffPrev = Math.abs(dataArray[left - 1].time - targetTime);
                if (diffPrev < diffLeft) {
                    return dataArray[left - 1];
                }
            }

            return dataArray[left];
        }

        const CROSSHAIR_TOLERANCE = 60;  // seconds for 1m charts

        function syncCharts(chart1, series1, chart2, series2, dataArray, label) {
            chart1.subscribeCrosshairMove(param => {
                // Don't sync during interactions (but don't clear measurement - keep it sticky)
                if (isAnyInteraction()) return;

                try {
                    if (param && param.time != null && param.point && param.seriesData) {
                        const data = param.seriesData.get(series1);
                        const price = data ? (data.close ?? data.value) : null;
                        const targetData = dataArray;
                        if (price == null || !isFinite(price)) return;
                        if (!chart2 || !series2 || !targetData || targetData.length === 0) return;

                        const nearestBar = findNearestTime(targetData, param.time);
                        if (!nearestBar || nearestBar.time == null) return;

                        const timeDelta = Math.abs(nearestBar.time - param.time);
                        if (timeDelta > CROSSHAIR_TOLERANCE) return;

                        const nearestPrice = nearestBar.close ?? nearestBar.value ?? price;
                        if (nearestPrice == null || !isFinite(nearestPrice)) return;

                        const visRange = chart2.timeScale().getVisibleRange();
                        if (!visRange || !isFinite(visRange.from) || !isFinite(visRange.to)) return;
                        if (nearestBar.time < visRange.from || nearestBar.time > visRange.to) return;

                        try {
                            chart2.setCrosshairPosition(nearestPrice, nearestBar.time, series2);
                        } catch (syncErr) {
                            chartWarn('crosshair sync failed', { error: syncErr?.message, time: nearestBar.time });
                        }
                    } else if (!param || !param.point) {
                        try { chart2.clearCrosshairPosition(); } catch(e) {}
                        // Don't clear measurement - keep it sticky
                    }
                } catch (e) {
                    chartWarn('syncCharts error', { error: e?.message });
                }
            });
        }
        // Hide crosshair when leaving chart wrappers (but keep measurement sticky)
        [
            { el: document.getElementById('es-realtime'), chart: esRtChart, target: btcRtChart },
            { el: document.getElementById('btc-realtime'), chart: btcRtChart, target: esRtChart },
            { el: document.getElementById('es-historical'), chart: esHistChart, target: btcHistChart },
            { el: document.getElementById('btc-historical'), chart: btcHistChart, target: esHistChart },
        ].forEach(({ el, chart, target }) => {
            if (!el || !chart || !target) return;
            el.addEventListener('mouseleave', () => {
                try { chart.clearCrosshairPosition(); } catch(e) {}
                try { target.clearCrosshairPosition(); } catch(e) {}
                // Don't clear measurement on mouseleave - keep it sticky
                // User must click Measure button or press Escape to clear
            });
        });
        // Data storage for charts (IMMUTABLE bars - ticks don't modify these)
        let esData = [];
        let btcData = [];
        let esHistData = [];
        let btcHistData = [];

        // Anchor mode toggles
        document.getElementById('anchor-globex')?.addEventListener('click', () => applyEsAnchor(ANCHOR_MODES.GLOBEX));
        document.getElementById('anchor-cash')?.addEventListener('click', () => applyEsAnchor(ANCHOR_MODES.CASH));

        // Range measurement toggle (button OR Shift+click)
        let measureMode = false;
        const measureBtn = document.getElementById('measure-toggle');
        if (measureBtn) {
            measureBtn.addEventListener('click', () => {
                measureMode = !measureMode;
                measureBtn.classList.toggle('active', measureMode);
                // Clear any existing measurements when turning off
                if (!measureMode) {
                    clearAllMeasurements();
                }
            });
        }
        // Keyboard shortcuts: Shift to measure, Escape to clear
        let shiftMeasure = false;
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Shift') shiftMeasure = true;
            if (e.key === 'Escape') clearAllMeasurements();
        });
        window.addEventListener('keyup', (e) => { if (e.key === 'Shift') shiftMeasure = false; });

        // Sync registration deferred until data arrives (prevents null errors during init)
        let syncRegistered = false;
        function registerCrosshairSync() {
            if (syncRegistered) return;
            // Only register sync if we have data
            if (esData.length === 0 || btcData.length === 0) {
                chartWarn('sync deferred: waiting for data', { es: esData.length, btc: btcData.length });
                return;
            }
            syncRegistered = true;
            // Sync real-time charts (pass data arrays for time range validation)
            syncCharts(esRtChart, esRtSeries, btcRtChart, btcRtSeries, btcData, 'ES');
            syncCharts(btcRtChart, btcRtSeries, esRtChart, esRtSeries, esData, 'BTC');
            // Sync historical charts
            syncCharts(esHistChart, esHistSeries, btcHistChart, btcHistSeries, btcHistData, 'ES');
            syncCharts(btcHistChart, btcHistSeries, esHistChart, esHistSeries, esHistData, 'BTC');
            console.log('[SYNC] Crosshair sync registered after data loaded');
        }

        // Current incomplete bar tracking (separate from completed bars)
        let currentEsBar = null;
        let currentBtcBar = null;

        // Current incomplete HOURLY bar tracking (for historical charts)
        let currentEsHourBar = null;
        let currentBtcHourBar = null;

        let lastEsPrice = null;
        let lastBtcPrice = null;
        let tickCount = 0;
        let lastTickTime = Date.now();

        // Latency tracking
        let latencySum = 0;
        let latencyCount = 0;
        let avgLatency = 0;

        // Update rate counter and latency every second
        setInterval(() => {
            const now = Date.now();
            const elapsed = (now - lastTickTime) / 1000;
            const rate = Math.round(tickCount / elapsed);
            document.getElementById('btc-rate').textContent = rate;

            // Update latency display
            if (latencyCount > 0) {
                avgLatency = Math.round(latencySum / latencyCount);
                const latencyEl = document.getElementById('latency-display');
                latencyEl.textContent = avgLatency + 'ms';
                latencyEl.classList.remove('slow', 'very-slow');
                if (avgLatency > 100) latencyEl.classList.add('very-slow');
                else if (avgLatency > 50) latencyEl.classList.add('slow');
            }

            tickCount = 0;
            latencySum = 0;
            latencyCount = 0;
            lastTickTime = now;
        }, 1000);

        // Pending DOM updates (batched with requestAnimationFrame)
        let pendingUpdates = {};
        let rafScheduled = false;

        function scheduleUpdate(key, fn) {
            pendingUpdates[key] = fn;
            if (!rafScheduled) {
                rafScheduled = true;
                requestAnimationFrame(flushUpdates);
            }
        }

        function flushUpdates() {
            const updates = pendingUpdates;
            pendingUpdates = {};
            rafScheduled = false;
            for (const fn of Object.values(updates)) {
                fn();
            }
        }

        // ========== RANGE MEASUREMENT ==========
        function getPriceFromCoordinate(series, chart, y) {
            // LightweightCharts v4.1.0 - use series.coordinateToPrice directly
            try {
                // Method 1: Direct series method (LWC v4+)
                if (typeof series.coordinateToPrice === 'function') {
                    const val = series.coordinateToPrice(y);
                    if (val != null && isFinite(val)) return val;
                }
                // Method 2: Try chart's right price scale
                const rightScale = chart.priceScale('right');
                if (rightScale && typeof rightScale.coordinateToPrice === 'function') {
                    const val = rightScale.coordinateToPrice(y);
                    if (val != null && isFinite(val)) return val;
                }
                // Method 3: Try chart's left price scale
                const leftScale = chart.priceScale('left');
                if (leftScale && typeof leftScale.coordinateToPrice === 'function') {
                    const val = leftScale.coordinateToPrice(y);
                    if (val != null && isFinite(val)) return val;
                }
            } catch (e) {
                // Silently fail - price conversion not critical
            }
            return null;
        }

        function setupRangeMeasure(containerId, chart, series, getDataArray) {
            const container = document.getElementById(containerId);
            if (!container || !chart || !series) return { clear() {} };

            const rect = document.createElement('div');
            rect.className = 'measure-rect';
            rect.style.display = 'none';
            const label = document.createElement('div');
            label.className = 'measure-label';
            label.style.display = 'none';
            container.appendChild(rect);
            container.appendChild(label);

            let start = null;
            let locked = false;  // TradingView-style: second click locks the measurement

            function clear() {
                start = null;
                locked = false;
                rect.style.display = 'none';
                label.style.display = 'none';
            }

            function pickSeries(point) {
                let targetSeries = series;
                let seriesLabel = '';

                // For overlay: choose nearest series at the click time (not last value)
                if (chart === overlayChart && overlayEsSeries && overlayBtcSeries) {
                    const clickTime = chart.timeScale().coordinateToTime(point.x);
                    if (clickTime == null) return { targetSeries, seriesLabel };

                    // Find nearest data points at/around the click time
                    function nearestData(dataArr, t) {
                        if (!dataArr || dataArr.length === 0) return null;
                        // binary search for nearest time
                        let l = 0, r = dataArr.length - 1;
                        while (l < r) {
                            const m = Math.floor((l + r) / 2);
                            if (dataArr[m].time < t) l = m + 1; else r = m;
                        }
                        const cand = dataArr[l];
                        const prev = l > 0 ? dataArr[l - 1] : null;
                        if (prev && Math.abs(prev.time - t) < Math.abs(cand.time - t)) return prev;
                        return cand;
                    }

                    const esPoint = nearestData(overlayEsData, clickTime);
                    const btcPoint = nearestData(overlayBtcData, clickTime);

                    const esY = esPoint && overlayEsSeries.priceToCoordinate ? overlayEsSeries.priceToCoordinate(esPoint.value) : null;
                    const btcY = btcPoint && overlayBtcSeries.priceToCoordinate ? overlayBtcSeries.priceToCoordinate(btcPoint.close || btcPoint.value || btcPoint.price) : null;
                    const dyEs = esY != null && point?.y != null ? Math.abs(point.y - esY) : Number.POSITIVE_INFINITY;
                    const dyBtc = btcY != null && point?.y != null ? Math.abs(point.y - btcY) : Number.POSITIVE_INFINITY;

                    if (dyEs < dyBtc) {
                        targetSeries = overlayEsSeries;
                        seriesLabel = 'ES %';
                    } else {
                        targetSeries = overlayBtcSeries;
                        seriesLabel = 'BTC $';
                    }
                }
                return { targetSeries, seriesLabel };
            }

            function updateSelection(point) {
                if (!start || !point || point.x == null || point.y == null) return;

                // Use series chosen at anchor
                const targetSeries = start.series || series;
                const seriesLabel = start.seriesLabel || '';

                // Data array depends on chosen series (overlay needs special handling)
                let dataArr = getDataArray ? getDataArray() : [];
                if (chart === overlayChart) {
                    if (targetSeries === overlayEsSeries) dataArr = overlayEsData || [];
                    else if (targetSeries === overlayBtcSeries) dataArr = overlayBtcData || [];
                }
                if (!dataArr || dataArr.length === 0) return;

                // Convert pixel to time/price (use safe helper for price)
                const endTime = chart.timeScale().coordinateToTime(point.x);
                const endPrice = getPriceFromCoordinate(targetSeries, chart, point.y);
                if (endTime == null || endPrice == null || !isFinite(endPrice)) return;

                if (start.time == null) return;

                // Coordinates - re-convert from time/price each frame to handle live scale shifts
                // This fixes the "drift" bug on overlay where stored pixels become stale
                let x1 = chart.timeScale().timeToCoordinate(start.time);
                let y1 = start.series && typeof start.series.priceToCoordinate === 'function'
                    ? start.series.priceToCoordinate(start.price)
                    : start.y;
                // Fallback to stored pixels if conversion fails
                if (x1 == null || !isFinite(x1)) x1 = start.x;
                if (y1 == null || !isFinite(y1)) y1 = start.y;
                const x2 = point.x;
                const y2 = point.y;
                if ([x1, y1, x2, y2].some(v => v == null || !isFinite(v))) return;

                const left = Math.min(x1, x2);
                const width = Math.abs(x2 - x1);
                const top = Math.min(y1, y2);
                const height = Math.abs(y2 - y1);

                rect.style.display = 'block';
                rect.style.left = `${left}px`;
                rect.style.top = `${top}px`;
                rect.style.width = `${width}px`;
                rect.style.height = `${height}px`;

                // Validate start.price before calculations
                if (start.price == null || !isFinite(start.price)) return;
                const priceDiff = endPrice - start.price;
                const pct = Math.abs(start.price) > 1e-6 ? (priceDiff / start.price) * 100 : null;

                let bars = 0;
                let vol = 0;
                const tMin = Math.min(start.time, endTime);
                const tMax = Math.max(start.time, endTime);
                const within = dataArr.filter(d => d.time >= tMin && d.time <= tMax);
                if (within.length > 0) {
                    bars = within.length;
                    vol = within.reduce((s, d) => s + (d.volume || 0), 0);
                }

                const seconds = Math.abs(endTime - start.time);
                const minutes = Math.round(seconds / 60);

                label.style.display = 'block';
                label.style.left = `${left + width / 2}px`;
                label.style.top = `${top - 28}px`;
                label.style.transform = 'translateX(-50%)';

                // TV-style coloring: blue for up, red for down
                const isUp = priceDiff >= 0;
                rect.style.background = isUp ? 'rgba(66,165,245,0.18)' : 'rgba(239,83,80,0.18)';
                rect.style.borderColor = isUp ? 'rgba(66,165,245,0.8)' : 'rgba(239,83,80,0.8)';
                label.style.background = isUp ? 'rgba(28,50,78,0.95)' : 'rgba(78,28,32,0.95)';
                label.style.borderColor = isUp ? 'rgba(66,165,245,0.8)' : 'rgba(239,83,80,0.8)';

                const isPercentSeries = seriesLabel.includes('%');
                const diffDisplay = isPercentSeries ? `${priceDiff.toFixed(2)}%` : priceDiff.toFixed(2);
                const pctDisplay = isPercentSeries ? '' : ` (${isUp ? '+' : ''}${pct != null ? pct.toFixed(2) : '0.00'}%)`;
                const seriesTag = seriesLabel ? ` · ${seriesLabel}` : '';
                const volDisplay = vol ? ` · Vol ${vol.toFixed(0)}` : '';
                label.textContent = `${diffDisplay}${pctDisplay}${seriesTag} · ${bars} bars · ${minutes}m${volDisplay}`;
            }

            // TradingView-style measurement:
            // 1st click: set start anchor, measurement follows mouse
            // 2nd click: lock measurement in place
            // 3rd click: start new measurement (clears old one)
            chart.subscribeClick(param => {
                if (!(measureMode || shiftMeasure) || !param || !param.point) return;
                const { targetSeries, seriesLabel } = pickSeries(param.point);
                const time = chart.timeScale().coordinateToTime(param.point.x);
                const price = getPriceFromCoordinate(targetSeries, chart, param.point.y);
                if (time == null || price == null || !isFinite(price)) return;

                if (!start) {
                    // First click: set start anchor
                    start = { x: param.point.x, y: param.point.y, time, price, series: targetSeries, seriesLabel };
                    locked = false;
                    updateSelection(param.point);
                } else if (!locked) {
                    // Second click: lock the measurement
                    locked = true;
                    updateSelection(param.point);  // Final update with click position
                } else {
                    // Third click: start new measurement
                    start = { x: param.point.x, y: param.point.y, time, price, series: targetSeries, seriesLabel };
                    locked = false;
                    updateSelection(param.point);
                }
            });

            chart.subscribeCrosshairMove(param => {
                // Don't update if locked (measurement is finalized)
                if (locked) return;
                if (!start) return;
                if (!param || !param.point) return;
                if (isDragging) return;
                updateSelection(param.point);
            });

            return { clear };
        }

        const measurementManagers = [];
        function clearAllMeasurements() {
            measurementManagers.forEach(m => m && m.clear && m.clear());
        }

        // Range measurement per chart (Shift+click to measure)
        measurementManagers.push(setupRangeMeasure('es-realtime', esRtChart, esRtSeries, () => esData));
        measurementManagers.push(setupRangeMeasure('btc-realtime', btcRtChart, btcRtSeries, () => btcData));
        measurementManagers.push(setupRangeMeasure('es-historical', esHistChart, esHistSeries, () => esHistData));
        measurementManagers.push(setupRangeMeasure('btc-historical', btcHistChart, btcHistSeries, () => btcHistData));
        // Overlay chart (correlation) - uses BTC candlestick series for measurement
        measurementManagers.push(setupRangeMeasure('overlay-main-chart', overlayChart, overlayBtcSeries, () => overlayBtcData));

        // Ultra-fast price update with requestAnimationFrame batching
        function updatePrice(element, price, lastPrice) {
            if (!element || price === undefined || price === null) return;
            scheduleUpdate('price-' + element.id, () => {
                element.textContent = price.toFixed(2);
                element.classList.remove('up', 'down');
                if (lastPrice !== null) {
                    element.classList.add(price >= lastPrice ? 'up' : 'down');
                }
            });
        }

        // Base prices for % change calculation
        let esBasePrice = null;
        let btcBasePrice = null;
        function applyEsAnchor(mode) {
            esAnchorMode = mode;
            esAnchorTs = computeAnchorTimestamp(mode);
            const base = findBasePrice(esData, esAnchorTs);
            if (base != null && isFinite(base)) {
                esBasePrice = base;
                overlayEsBase = base;
            } else if (esData.length > 0) {
                esBasePrice = esData[0].close;
                overlayEsBase = esBasePrice;
            }
            // Recompute overlay and header % after base change
            updatePctChange();
            updateOverlayChart();
            // Toggle button states
            document.getElementById('anchor-globex')?.classList.toggle('active', esAnchorMode === ANCHOR_MODES.GLOBEX);
            document.getElementById('anchor-cash')?.classList.toggle('active', esAnchorMode === ANCHOR_MODES.CASH);
        }
        function refreshAnchorIfNeeded() {
            const newAnchor = computeAnchorTimestamp(esAnchorMode);
            if (newAnchor !== esAnchorTs) {
                applyEsAnchor(esAnchorMode);
            }
        }
        setInterval(refreshAnchorIfNeeded, 60 * 1000);  // check every minute

        // Update % change display
        function updatePctChange() {
            if (esBasePrice && lastEsPrice) {
                const pct = ((lastEsPrice - esBasePrice) / esBasePrice) * 100;
                const el = document.getElementById('es-pct');
                el.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
                el.className = 'price-pct ' + (pct >= 0 ? 'up' : 'down');
            }
            if (btcBasePrice && lastBtcPrice) {
                const pct = ((lastBtcPrice - btcBasePrice) / btcBasePrice) * 100;
                const el = document.getElementById('btc-pct');
                el.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
                el.className = 'price-pct ' + (pct >= 0 ? 'up' : 'down');
            }
        }

        // Update historical (hourly) charts with live tick data
        function updateHourlyBar(symbol, price) {
            try {
                if (price == null || !isFinite(price)) return;

                const now = Math.floor(Date.now() / 1000 / 3600) * 3600;  // Current hour boundary

                if (symbol === 'ES') {
                    if (esHistData.length === 0) return;
                    if (isAnyInteraction()) return;

                    const lastBar = esHistData[esHistData.length - 1];
                    if (!lastBar || lastBar.close == null) return;

                    if (!currentEsHourBar || currentEsHourBar.time !== now) {
                        currentEsHourBar = {
                            time: now,
                            open: lastBar.close,
                            high: price,
                            low: price,
                            close: price,
                            volume: 0
                        };
                        if (lastBar.time < now) {
                            esHistData.push(currentEsHourBar);
                        }
                    } else {
                        currentEsHourBar.high = Math.max(currentEsHourBar.high, price);
                        currentEsHourBar.low = Math.min(currentEsHourBar.low, price);
                        currentEsHourBar.close = price;
                    }
                    throttledChartOp('hourly-es', 50, () => { esHistSeries.update(currentEsHourBar); });
                } else if (symbol === 'BTC') {
                    if (btcHistData.length === 0) return;
                    if (isAnyInteraction()) return;

                    const lastBar = btcHistData[btcHistData.length - 1];
                    if (!lastBar || lastBar.close == null) return;

                    if (!currentBtcHourBar || currentBtcHourBar.time !== now) {
                        currentBtcHourBar = {
                            time: now,
                            open: lastBar.close,
                            high: price,
                            low: price,
                            close: price,
                            volume: 0
                        };
                        if (lastBar.time < now) {
                            btcHistData.push(currentBtcHourBar);
                        }
                    } else {
                        currentBtcHourBar.high = Math.max(currentBtcHourBar.high, price);
                        currentBtcHourBar.low = Math.min(currentBtcHourBar.low, price);
                        currentBtcHourBar.close = price;
                    }
                    throttledChartOp('hourly-btc', 50, () => { btcHistSeries.update(currentBtcHourBar); });
                }
            } catch (e) {
                // Silently ignore hourly bar update errors
            }
        }

        // Update correlation display from server data (COMPACT VERSION)
        function updateCorrelationDisplay(data) {
            // Color mapping
            function getColor(corr) {
                const abs = Math.abs(corr);
                if (abs > 0.7) return '#00C853';  // Green - strong
                if (abs > 0.4) return '#FFD600';  // Yellow - moderate
                if (abs > 0.2) return '#42A5F5';  // Blue - weak
                return '#FF1744';  // Red - divergence
            }

            // Update each timeframe in compact header
            const timeframes = ['1m', '5m', '15m', '1h'];
            timeframes.forEach(tf => {
                if (data[tf]) {
                    const el = document.getElementById('corr-' + tf);
                    if (el) {
                        const corr = data[tf].correlation;
                        el.textContent = corr.toFixed(2);
                        el.style.color = getColor(corr);
                    }
                }
            });

            // Update lead/lag display - use the strongest timeframe
            const bestTf = data['1h'] && Math.abs(data['1h'].correlation) > 0.5 ? '1h' : '1m';
            if (data[bestTf]) {
                const leadLag = data[bestTf].lead_lag;
                const leader = data[bestTf].leader;

                const valueEl = document.getElementById('lead-lag-value');
                if (valueEl) {
                    if (Math.abs(leadLag) < 1) {
                        valueEl.textContent = 'SYNC';
                        valueEl.style.color = '#787b86';
                    } else {
                        const unit = bestTf === '1h' ? 'h' : 'm';
                        valueEl.textContent = `${leader}+${Math.abs(leadLag)}${unit}`;
                        valueEl.style.color = leader === 'ES' ? '#26a69a' : '#42A5F5';
                    }
                }
            }

            // Generate Trading Signal
            updateTradingSignal(data);
        }

        // Generate actionable trading signal (COMPACT)
        function updateTradingSignal(data) {
            const signalEl = document.getElementById('trading-signal');
            const signalBox = document.getElementById('signal-box');

            if (!signalEl) return;

            if (!data['1h'] || !lastEsPrice || !lastBtcPrice) {
                signalEl.textContent = 'WAIT';
                signalEl.style.color = '#787b86';
                return;
            }

            const hourlyCorr = data['1h'].correlation;

            // Calculate recent moves (last 5 bars)
            const esMove = esData.length >= 6 ?
                ((esData[esData.length-1].close - esData[esData.length-6].close) / esData[esData.length-6].close) * 100 : 0;
            const btcMove = btcData.length >= 6 ?
                ((btcData[btcData.length-1].close - btcData[btcData.length-6].close) / btcData[btcData.length-6].close) * 100 : 0;

            // Trading logic based on correlation
            if (Math.abs(hourlyCorr) > 0.7) {
                // Strong correlation - expect them to move together
                if (Math.abs(btcMove) > 0.3 && Math.abs(esMove) < 0.1) {
                    signalEl.textContent = btcMove > 0 ? 'ES UP?' : 'ES DN?';
                    signalEl.style.color = btcMove > 0 ? '#00C853' : '#ef5350';
                    if (signalBox) signalBox.classList.add('highlight');
                } else if (Math.abs(esMove) > 0.1 && Math.abs(btcMove) < 0.3) {
                    signalEl.textContent = esMove > 0 ? 'BTC UP?' : 'BTC DN?';
                    signalEl.style.color = esMove > 0 ? '#00C853' : '#ef5350';
                    if (signalBox) signalBox.classList.add('highlight');
                } else {
                    signalEl.textContent = 'SYNC';
                    signalEl.style.color = '#00C853';
                    if (signalBox) signalBox.classList.remove('highlight');
                }
            } else if (Math.abs(hourlyCorr) < 0.2) {
                signalEl.textContent = 'DIVG';
                signalEl.style.color = '#FF1744';
                if (signalBox) signalBox.classList.remove('highlight');
            } else {
                signalEl.textContent = 'NEUT';
                signalEl.style.color = '#787b86';
                if (signalBox) signalBox.classList.remove('highlight');
            }
        }

        // WebSocket connection
        function connect() {
            const ws = new WebSocket('ws://' + window.location.host + '/ws');

            ws.onopen = () => {
                document.getElementById('status-dot').classList.add('connected');
            };

            ws.onclose = () => {
                document.getElementById('status-dot').classList.remove('connected');
                setTimeout(connect, 2000);
            };

            ws.onmessage = (event) => {
                let msg;
                try {
                    msg = JSON.parse(event.data);
                } catch (e) {
                    console.warn('Failed to parse message:', e);
                    return;
                }

                if (msg.type === 'init') {
                    // Set contract
                    const esContractEl = document.getElementById('es-contract');
                    if (esContractEl && msg.es_contract) esContractEl.textContent = msg.es_contract;

                    // Load backfill data (COMPLETED bars only)
                    if (msg.es_backfill && msg.es_backfill.length) {
                        esData = msg.es_backfill;
                        try { esRtSeries.setData(esData); } catch(e) {}
                        lastEsPrice = esData[esData.length - 1].close;
                        updatePrice(document.getElementById('es-price'), lastEsPrice, null);
                    }
                    if (msg.btc_backfill && msg.btc_backfill.length) {
                        btcData = msg.btc_backfill;
                        try { btcRtSeries.setData(btcData); } catch(e) {}
                        lastBtcPrice = btcData[btcData.length - 1].close;
                        btcBasePrice = btcData[0].close;  // Set base for % change
                        updatePrice(document.getElementById('btc-price'), lastBtcPrice, null);
                    }

                    // Load historical
                    if (msg.es_historical && msg.es_historical.length) {
                        esHistData = msg.es_historical;
                        try { esHistSeries.setData(esHistData); } catch(e) {}
                    }
                    if (msg.btc_historical && msg.btc_historical.length) {
                        btcHistData = msg.btc_historical;
                        try { btcHistSeries.setData(btcHistData); } catch(e) {}
                    }

                    // Anchor base prices (ES uses session anchor, BTC uses first bar)
                    if (btcData.length > 0) {
                        btcBasePrice = btcData[0].close;
                    }
                    if (esData.length > 0) {
                        // Ensure ES base price is initialized (was missing)
                        esBasePrice = esData[0].close;
                        applyEsAnchor(esAnchorMode);
                    }

                    // Update % change display
                    updatePctChange();

                    // Update TradingView-style overlay chart
                    updateOverlayChart();

                    // Update correlation display if provided
                    if (msg.correlation) {
                        updateCorrelationDisplay(msg.correlation);
                    }

                    // Register crosshair sync NOW that data is loaded
                    registerCrosshairSync();
                }
                else if (msg.type === 'bar') {
                    // Completed bar - add to immutable array
                    const bar = msg.data;
                    if (msg.symbol === 'ES') {
                        esData.push(bar);
                        if (esData.length > 1440) esData.shift();
                        try { esRtSeries.setData(esData); } catch(e) {}  // Reset data to ensure clean state
                        updatePrice(document.getElementById('es-price'), bar.close, lastEsPrice);
                        lastEsPrice = bar.close;
                        currentEsBar = null;  // Reset current bar tracking
                    } else if (msg.symbol === 'BTC') {
                        btcData.push(bar);
                        if (btcData.length > 1440) btcData.shift();
                        try { btcRtSeries.setData(btcData); } catch(e) {}  // Reset data to ensure clean state
                        updatePrice(document.getElementById('btc-price'), bar.close, lastBtcPrice);
                        lastBtcPrice = bar.close;
                        currentBtcBar = null;  // Reset current bar tracking
                    }
                    // Update overlay and % change on bar completion
                    updatePctChange();
                    updateOverlayChart();
                }
                else if (msg.type === 'ticks') {
                    // BATCHED TICKS: Process multiple ticks efficiently
                    const now = Math.floor(Date.now() / 1000 / 60) * 60;
                    const receiveTime = Date.now();

                    for (const tick of msg.data) {
                        tickCount++;
                        const symbol = tick.s;
                        const price = tick.p;
                        const ts = tick.t;

                        // Calculate latency
                        if (ts) {
                            const latency = receiveTime - ts;
                            if (latency > 0 && latency < 5000) {
                                latencySum += latency;
                                latencyCount++;
                            }
                        }

                        if (symbol === 'BTC') {
                            updatePrice(document.getElementById('btc-price'), price, lastBtcPrice);
                            lastBtcPrice = price;

                            if (!currentBtcBar || currentBtcBar.time !== now) {
                                const lastComplete = btcData.length > 0 ? btcData[btcData.length - 1] : null;
                                currentBtcBar = {
                                    time: now,
                                    open: lastComplete ? lastComplete.close : price,
                                    high: price, low: price, close: price
                                };
                            } else {
                                currentBtcBar.high = Math.max(currentBtcBar.high, price);
                                currentBtcBar.low = Math.min(currentBtcBar.low, price);
                                currentBtcBar.close = price;
                        }
                        throttledChartOp('batch-btc', 30, () => { btcRtSeries.update(currentBtcBar); });
                        updateHourlyBar('BTC', price);
                        updateOverlayTick('BTC', price);  // Update overlay chart
                    } else if (symbol === 'ES') {
                            updatePrice(document.getElementById('es-price'), price, lastEsPrice);
                            lastEsPrice = price;
                            if (esBasePrice == null && esData.length > 0) {
                                esBasePrice = esData[0].close;
                            }

                            if (!currentEsBar || currentEsBar.time !== now) {
                                const lastComplete = esData.length > 0 ? esData[esData.length - 1] : null;
                                currentEsBar = {
                                    time: now,
                                    open: lastComplete ? lastComplete.close : price,
                                    high: price, low: price, close: price
                                };
                            } else {
                                currentEsBar.high = Math.max(currentEsBar.high, price);
                                currentEsBar.low = Math.min(currentEsBar.low, price);
                                currentEsBar.close = price;
                            }
                        throttledChartOp('batch-es', 30, () => { esRtSeries.update(currentEsBar); });
                        updateHourlyBar('ES', price);
                        updateOverlayTick('ES', price);  // Update overlay chart
                    }
                    }
                    updatePctChange();
                }
                else if (msg.type === 'tick') {
                    // LEGACY: Single tick (for backwards compatibility)
                    tickCount++;
                    const now = Math.floor(Date.now() / 1000 / 60) * 60;
                    const receiveTime = Date.now();

                    if (msg.ts) {
                        const latency = receiveTime - msg.ts;
                        if (latency > 0 && latency < 5000) {
                            latencySum += latency;
                            latencyCount++;
                        }
                    }

                    if (msg.symbol === 'BTC') {
                        updatePrice(document.getElementById('btc-price'), msg.price, lastBtcPrice);
                        lastBtcPrice = msg.price;

                        if (!currentBtcBar || currentBtcBar.time !== now) {
                            const lastComplete = btcData.length > 0 ? btcData[btcData.length - 1] : null;
                            currentBtcBar = {
                                time: now,
                                open: lastComplete ? lastComplete.close : msg.price,
                                high: msg.price, low: msg.price, close: msg.price
                            };
                        } else {
                            currentBtcBar.high = Math.max(currentBtcBar.high, msg.price);
                            currentBtcBar.low = Math.min(currentBtcBar.low, msg.price);
                            currentBtcBar.close = msg.price;
                        }
                        throttledChartOp('rt-btc', 30, () => { btcRtSeries.update(currentBtcBar); });
                        updateHourlyBar('BTC', msg.price);
                        updateOverlayTick('BTC', msg.price);  // Update overlay chart
                    } else if (msg.symbol === 'ES') {
                        updatePrice(document.getElementById('es-price'), msg.price, lastEsPrice);
                        lastEsPrice = msg.price;
                        if (esBasePrice == null && esData.length > 0) {
                            esBasePrice = esData[0].close;
                        }

                        if (!currentEsBar || currentEsBar.time !== now) {
                            const lastComplete = esData.length > 0 ? esData[esData.length - 1] : null;
                            currentEsBar = {
                                time: now,
                                open: lastComplete ? lastComplete.close : msg.price,
                                high: msg.price, low: msg.price, close: msg.price
                            };
                        } else {
                            currentEsBar.high = Math.max(currentEsBar.high, msg.price);
                            currentEsBar.low = Math.min(currentEsBar.low, msg.price);
                            currentEsBar.close = msg.price;
                        }
                        throttledChartOp('rt-es', 30, () => { esRtSeries.update(currentEsBar); });
                        updateHourlyBar('ES', msg.price);
                        updateOverlayTick('ES', msg.price);  // Update overlay chart
                    }
                    updatePctChange();
                }
                else if (msg.type === 'correlation') {
                    // Update correlation display with server-calculated values
                    updateCorrelationDisplay(msg.data);
                }
            };
        }

        // Resize handler - use RAF for smooth resize
        let resizeRaf = null;
        window.addEventListener('resize', () => {
            if (resizeRaf) cancelAnimationFrame(resizeRaf);
            resizeRaf = requestAnimationFrame(() => {
                try {
                    esRtChart.applyOptions({ width: document.getElementById('es-realtime').offsetWidth });
                    btcRtChart.applyOptions({ width: document.getElementById('btc-realtime').offsetWidth });
                    esHistChart.applyOptions({ width: document.getElementById('es-historical').offsetWidth });
                    btcHistChart.applyOptions({ width: document.getElementById('btc-historical').offsetWidth });
                    // CRITICAL: Both overlay charts must have SAME width for alignment
                    const overlayWidth = document.getElementById('overlay-main-chart').offsetWidth;
                    overlayChart.applyOptions({ width: overlayWidth });
                    overlayVolChart.applyOptions({ width: overlayWidth });
                    // Re-sync after resize
                    syncVolToMain();
                } catch(e) {
                    // Resize during transition - ignore
                }
            });
        });

        // Start
        connect();
    </script>
</body>
</html>'''

        output_dir = Path(__file__).parent.parent / 'output'
        output_dir.mkdir(exist_ok=True)

        with open(output_dir / 'live_dashboard.html', 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"[OK] Generated live dashboard")

    def _generate_micro_html(self):
        """Generate a slim microstructure-focused dashboard (remove historical panes)."""
        # Reuse the main HTML and strip historical sections after load.
        html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ES/BTC Micro View</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>
    <div id="micro-root">Loading micro view...</div>
    <script>
        // Load the main dashboard HTML, then remove historical panes.
        fetch('/').then(r => r.text()).then(html => {
            document.open();
            document.write(html);
            document.close();
            // Remove historical chart wrappers
            document.querySelectorAll('.chart-wrapper.historical').forEach(el => el.remove());
            // Remove any section titles that reference Historical
            document.querySelectorAll('.section-title').forEach(el => {
                if (el.textContent && el.textContent.toLowerCase().includes('historical')) {
                    el.remove();
                }
            });
            // Remove empty grids left behind
            document.querySelectorAll('.charts-container').forEach(el => {
                if (!el.querySelector('.chart-wrapper')) el.remove();
            });
        });
    </script>
</body>
</html>'''

        output_dir = Path(__file__).parent.parent / 'output'
        output_dir.mkdir(exist_ok=True)

        with open(output_dir / 'micro_dashboard.html', 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"[OK] Generated micro dashboard")

async def main():
    server = LiveDashboardServer()
    await server.run()


if __name__ == '__main__':
    asyncio.run(main())

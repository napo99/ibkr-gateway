"""
Live WebSocket Server for Real-Time Dashboard
Streams ES + BTC prices to browser via WebSocket
WITH correlation analysis and lead/lag detection
"""

import asyncio
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
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
            'data': bar.to_dict()
        }))
        print(f"[ES] {bar.timestamp.strftime('%H:%M:%S')} Close: {bar.close:.2f}")

        # Trigger correlation calculation after each bar
        asyncio.create_task(self._calculate_and_broadcast_correlation())

    def _on_btc_bar(self, bar: OHLCV):
        """Callback when new BTC bar completes"""
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
            'data': bar.to_dict()
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
            es_df = self.ibkr.fetch_historical('1 D', '1 min')
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

        try:
            es_hist = self.ibkr.fetch_historical('7 D', '1 hour')
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
                        if price != last_price:
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
            if price and price != last_price[0]:
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

        # Setup web server
        app = web.Application()
        app.router.add_get('/', self.index_handler)
        app.router.add_get('/ws', self.websocket_handler)

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

    def _generate_live_html(self):
        """Generate the live WebSocket-powered dashboard with correlation analysis"""
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
        </div>
        <div class="status-section">
            <div class="status-dot" id="status-dot"></div>
            <span class="latency" id="latency-display">--ms</span>
            <span class="rate" id="btc-rate">0</span>/s
        </div>
    </div>

    <div class="measurement" id="measurement" style="display:none; position:fixed; background:#1a1a2e; padding:8px 12px; border-radius:4px; font-size:12px; z-index:1000; pointer-events:none;">
        <div>Time: <span id="m-time">--</span></div>
        <div>Price: <span id="m-price">--</span></div>
        <div style="color:#787b86">Move: <span id="m-move" style="color:#00C853">--</span></div>
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
        // Aggressively suppress LightweightCharts "Value is null" errors
        (function() {
            const originalError = console.error;
            console.error = function(...args) {
                const msg = args.join(' ');
                if (msg.includes('Value is null') || msg.includes('lightweight-charts')) return;
                originalError.apply(console, args);
            };
        })();
        window.onerror = function(msg) {
            if (msg && (msg.includes('Value is null') || msg.includes('lightweight-charts'))) return true;
            return false;
        };
        window.addEventListener('error', function(e) {
            if (e.message && (e.message.includes('Value is null') || e.message.includes('lightweight-charts'))) {
                e.preventDefault(); e.stopPropagation(); return true;
            }
        }, true);
        window.addEventListener('unhandledrejection', function(e) {
            if (e.reason && String(e.reason).includes('Value is null')) { e.preventDefault(); return true; }
        });

        // Helper: validate range before time scale sync
        function isValidRange(range) {
            return range && range.from != null && range.to != null &&
                   typeof range.from === 'number' && typeof range.to === 'number' &&
                   isFinite(range.from) && isFinite(range.to) && range.from < range.to;
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
        let syncingOverlay = false;

        function syncVolToMain() {
            if (syncingOverlay) return;
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

        // Main chart drives the volume chart - sync on both events
        overlayChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            if (!syncingOverlay) syncVolToMain();
        });
        overlayChart.timeScale().subscribeVisibleTimeRangeChange(() => {
            if (!syncingOverlay) syncVolToMain();
        });

        // Store data for overlay
        let overlayBtcData = [];
        let overlayEsData = [];
        let overlayEsBase = null;
        let currentOverlayBtcBar = null;
        let currentOverlayEsBar = null;
        let overlayEsPriceLine = null;

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
                    }
                }
            } catch (e) {
                // Chart not ready yet - silently ignore
            }
        }

        // Re-position ES label when chart scales/zooms - use RAF for smooth updates
        let esPriceLabelRaf = null;
        overlayChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            if (esPriceLabelRaf) cancelAnimationFrame(esPriceLabelRaf);
            esPriceLabelRaf = requestAnimationFrame(() => {
                if (esData.length > 0 && overlayEsBase && overlayEsData.length > 0) {
                    const lastEs = esData[esData.length - 1];
                    const esPct = ((lastEs.close - overlayEsBase) / overlayEsBase) * 100;
                    updateEsPriceLabel(lastEs.close, esPct);
                }
            });
        });

        // Fast tick update for overlay chart (called on each tick)
        function updateOverlayTick(symbol, price) {
            try {
                if (price == null || !isFinite(price)) return;

                const now = Math.floor(Date.now() / 1000 / 60) * 60;

                if (symbol === 'BTC') {
                    // Update BTC candle
                    if (!currentOverlayBtcBar || currentOverlayBtcBar.time !== now) {
                        const lastClose = btcData.length > 0 ? btcData[btcData.length - 1].close : price;
                        currentOverlayBtcBar = { time: now, open: lastClose, high: price, low: price, close: price };
                    } else {
                        currentOverlayBtcBar.high = Math.max(currentOverlayBtcBar.high, price);
                        currentOverlayBtcBar.low = Math.min(currentOverlayBtcBar.low, price);
                        currentOverlayBtcBar.close = price;
                    }
                    overlayBtcSeries.update(currentOverlayBtcBar);

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
                    // Update ES % line
                    if (overlayEsBase && esData.length > 0) {
                        const esPct = ((price - overlayEsBase) / overlayEsBase) * 100;

                        if (!currentOverlayEsBar || currentOverlayEsBar.time !== now) {
                            currentOverlayEsBar = { time: now, value: esPct };
                        } else {
                            currentOverlayEsBar.value = esPct;
                        }
                        overlayEsSeries.update(currentOverlayEsBar);

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
        function updateOverlayChart() {
            if (btcData.length < 2 || esData.length < 2) return;

            // Use realtime data
            overlayBtcData = btcData.slice();
            overlayBtcSeries.setData(overlayBtcData);

            // Calculate ES % change from first bar
            if (!overlayEsBase && esData.length > 0) {
                overlayEsBase = esData[0].close;
            }

            if (overlayEsBase) {
                overlayEsData = esData.map(d => ({
                    time: d.time,
                    value: ((d.close - overlayEsBase) / overlayEsBase) * 100
                }));
                overlayEsSeries.setData(overlayEsData);
            }

            // Volume with color - normalize large BTC volumes
            const volData = btcData.map(d => ({
                time: d.time,
                value: d.volume || 0,
                color: d.close >= d.open ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)'
            })).filter(d => d.value > 0);
            overlayBtcVolSeries.setData(volData);

            // Sync time scales - volume follows main chart EXACTLY
            try {
                overlayChart.timeScale().fitContent();
                // Force perfect sync after a brief delay for rendering
                setTimeout(() => syncVolToMain(), 50);
                setTimeout(() => syncVolToMain(), 200);
            } catch(e) {}

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
                updateEsPriceLabel(lastEs.close, esPct);
            }
        }
        // ========== END: TradingView-Style Overlay Chart ==========

        // Charts are INDEPENDENT - each can be dragged/zoomed separately
        // Only crosshairs are synced (below) for visual comparison

        // Measurement state
        let measureStart = null;
        const measureEl = document.getElementById('measurement');

        // Sync crosshairs between paired charts with measurement
        // Track if user is dragging (don't sync during drag)
        let isDragging = false;
        document.addEventListener('mousedown', () => { isDragging = true; });
        document.addEventListener('mouseup', () => { isDragging = false; });

        function syncCharts(chart1, series1, chart2, series2, dataArray, label) {
            chart1.subscribeCrosshairMove(param => {
                // Don't sync during drag operations - this causes errors
                if (isDragging) return;

                try {
                    // Only process if this is from actual mouse hover (param.point exists)
                    if (param.time != null && param.point && param.seriesData) {
                        const data = param.seriesData.get(series1);
                        const price = data ? (data.close ?? data.value) : null;

                        if (price != null && typeof price === 'number' && isFinite(price)) {
                            // Only sync if target has data and time is in range
                            if (dataArray && dataArray.length > 0) {
                                const firstTime = dataArray[0].time;
                                const lastTime = dataArray[dataArray.length - 1].time;
                                if (param.time >= firstTime && param.time <= lastTime) {
                                    try {
                                        chart2.setCrosshairPosition(price, param.time, series2);
                                    } catch(e) {}
                                }
                            }

                            // Show measurement tooltip
                            const time = new Date(param.time * 1000);
                            document.getElementById('m-time').textContent = time.toLocaleTimeString();
                            document.getElementById('m-price').textContent = price.toFixed(2);

                            if (measureStart === null) measureStart = { time: param.time, price: price };
                            if (measureStart.price) {
                                const priceDiff = price - measureStart.price;
                                const pctMove = ((priceDiff / measureStart.price) * 100).toFixed(3);
                                const timeDiff = Math.round((param.time - measureStart.time) / 60);
                                const sign = priceDiff >= 0 ? '+' : '';
                                document.getElementById('m-move').textContent = `${sign}${priceDiff.toFixed(2)} (${sign}${pctMove}%) / ${timeDiff}min`;
                                document.getElementById('m-move').style.color = priceDiff >= 0 ? '#00C853' : '#ef5350';
                            }

                            if (measureEl) {
                                measureEl.style.display = 'block';
                                measureEl.style.left = (param.point.x + 20) + 'px';
                                measureEl.style.top = (param.point.y + 20) + 'px';
                            }
                        }
                    } else if (!param.point) {
                        // Mouse left chart area
                        try { chart2.clearCrosshairPosition(); } catch(e) {}
                        if (measureEl) measureEl.style.display = 'none';
                        measureStart = null;
                    }
                } catch (e) {}
            });
        }
        // Data storage for charts (IMMUTABLE bars - ticks don't modify these)
        let esData = [];
        let btcData = [];
        let esHistData = [];
        let btcHistData = [];

        // Sync real-time charts (pass data arrays for time range validation)
        syncCharts(esRtChart, esRtSeries, btcRtChart, btcRtSeries, btcData, 'ES');
        syncCharts(btcRtChart, btcRtSeries, esRtChart, esRtSeries, esData, 'BTC');
        // Sync historical charts
        syncCharts(esHistChart, esHistSeries, btcHistChart, btcHistSeries, btcHistData, 'ES');
        syncCharts(btcHistChart, btcHistSeries, esHistChart, esHistSeries, esHistData, 'BTC');

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
                    esHistSeries.update(currentEsHourBar);
                } else if (symbol === 'BTC') {
                    if (btcHistData.length === 0) return;

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
                    btcHistSeries.update(currentBtcHourBar);
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
            const esMove = esData.length > 5 ?
                ((esData[esData.length-1].close - esData[esData.length-6].close) / esData[esData.length-6].close) * 100 : 0;
            const btcMove = btcData.length > 5 ?
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
                        esRtSeries.setData(esData);
                        lastEsPrice = esData[esData.length - 1].close;
                        esBasePrice = esData[0].close;  // Set base for % change
                        updatePrice(document.getElementById('es-price'), lastEsPrice, null);
                    }
                    if (msg.btc_backfill && msg.btc_backfill.length) {
                        btcData = msg.btc_backfill;
                        btcRtSeries.setData(btcData);
                        lastBtcPrice = btcData[btcData.length - 1].close;
                        btcBasePrice = btcData[0].close;  // Set base for % change
                        updatePrice(document.getElementById('btc-price'), lastBtcPrice, null);
                    }

                    // Load historical
                    if (msg.es_historical && msg.es_historical.length) {
                        esHistData = msg.es_historical;
                        esHistSeries.setData(esHistData);
                    }
                    if (msg.btc_historical && msg.btc_historical.length) {
                        btcHistData = msg.btc_historical;
                        btcHistSeries.setData(btcHistData);
                    }

                    // Update % change display
                    updatePctChange();

                    // Update TradingView-style overlay chart
                    updateOverlayChart();

                    // Update correlation display if provided
                    if (msg.correlation) {
                        updateCorrelationDisplay(msg.correlation);
                    }
                }
                else if (msg.type === 'bar') {
                    // Completed bar - add to immutable array
                    const bar = msg.data;
                    if (msg.symbol === 'ES') {
                        esData.push(bar);
                        if (esData.length > 1440) esData.shift();
                        esRtSeries.setData(esData);  // Reset data to ensure clean state
                        updatePrice(document.getElementById('es-price'), bar.close, lastEsPrice);
                        lastEsPrice = bar.close;
                        currentEsBar = null;  // Reset current bar tracking
                    } else if (msg.symbol === 'BTC') {
                        btcData.push(bar);
                        if (btcData.length > 1440) btcData.shift();
                        btcRtSeries.setData(btcData);  // Reset data to ensure clean state
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
                            btcRtSeries.update(currentBtcBar);
                            updateHourlyBar('BTC', price);
                            updateOverlayTick('BTC', price);  // Update overlay chart
                        } else if (symbol === 'ES') {
                            updatePrice(document.getElementById('es-price'), price, lastEsPrice);
                            lastEsPrice = price;

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
                            esRtSeries.update(currentEsBar);
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
                        btcRtSeries.update(currentBtcBar);
                        updateHourlyBar('BTC', msg.price);
                        updateOverlayTick('BTC', msg.price);  // Update overlay chart
                    } else if (msg.symbol === 'ES') {
                        updatePrice(document.getElementById('es-price'), msg.price, lastEsPrice);
                        lastEsPrice = msg.price;

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
                        esRtSeries.update(currentEsBar);
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


async def main():
    server = LiveDashboardServer()
    await server.run()


if __name__ == '__main__':
    asyncio.run(main())

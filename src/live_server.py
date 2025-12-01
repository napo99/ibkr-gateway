"""
Live WebSocket Server for Real-Time Dashboard
Streams ES + BTC prices to browser via WebSocket
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from aiohttp import web
import aiohttp

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from data_sources import BinanceClient, IBKRClient, OHLCV, DataBuffer


class LiveDashboardServer:
    """WebSocket server that streams live data to browser"""

    def __init__(self, host='127.0.0.1', port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.running = False

        # Data sources
        self.ibkr = IBKRClient(symbol='ES', on_bar=self._on_es_bar)
        self.binance = BinanceClient(on_bar=self._on_btc_bar)

        # Historical data cache
        self.es_historical = []
        self.btc_historical = []
        self.es_backfill = []
        self.btc_backfill = []

        # Latest prices for live updates
        self.latest_es = None
        self.latest_btc = None

        # Tick streaming
        self.btc_ws = None

    async def _broadcast(self, data: dict):
        """Send data to all connected clients"""
        if not self.clients:
            return
        message = json.dumps(data)
        await asyncio.gather(
            *[client.send_str(message) for client in self.clients],
            return_exceptions=True
        )

    def _on_es_bar(self, bar: OHLCV):
        """Callback when new ES bar completes"""
        self.latest_es = bar
        asyncio.create_task(self._broadcast({
            'type': 'bar',
            'symbol': 'ES',
            'data': bar.to_dict()
        }))
        print(f"[ES] {bar.timestamp.strftime('%H:%M:%S')} Close: {bar.close:.2f}")

    def _on_btc_bar(self, bar: OHLCV):
        """Callback when new BTC bar completes"""
        self.latest_btc = bar
        asyncio.create_task(self._broadcast({
            'type': 'bar',
            'symbol': 'BTC',
            'data': bar.to_dict()
        }))
        print(f"[BTC] {bar.timestamp.strftime('%H:%M:%S')} Close: {bar.close:.2f}")

    async def _fetch_backfill(self):
        """Fetch last 30 mins of 1-min data for both assets"""
        print("[INIT] Fetching backfill data (last 30 mins)...")

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

    async def websocket_handler(self, request):
        """Handle WebSocket connections"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.clients.add(ws)
        print(f"[WS] Client connected ({len(self.clients)} total)")

        # Send initial data
        await ws.send_json({
            'type': 'init',
            'es_backfill': self.es_backfill,
            'btc_backfill': self.btc_backfill,
            'es_historical': self.es_historical,
            'btc_historical': self.btc_historical,
            'es_contract': self.ibkr.contract_symbol
        })

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
        """Stream BTC trades for real-time price updates (throttled to 50ms)"""
        import websockets
        url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
        last_broadcast = 0

        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    async for msg in ws:
                        if not self.running:
                            break
                        data = json.loads(msg)
                        price = float(data['p'])
                        now = asyncio.get_event_loop().time()

                        # Throttle to every 20ms (50 updates/sec) for faster real-time feel
                        if now - last_broadcast >= 0.02:
                            await self._broadcast({
                                'type': 'tick',
                                'symbol': 'BTC',
                                'price': price
                            })
                            last_broadcast = now
            except Exception as e:
                if self.running:
                    print(f"[BTC TICK] Error: {e}, reconnecting...")
                    await asyncio.sleep(1)

    async def _stream_es_ticks(self):
        """Stream ES ticks from IBKR market data (throttled to 100ms)"""
        last_broadcast = 0
        last_price = None

        # Subscribe to market data
        if self.ibkr._contract:
            self.ibkr.ib.reqMarketDataType(3)  # Delayed if no live subscription
            ticker = self.ibkr.ib.reqMktData(self.ibkr._contract, '', False, False)

            while self.running:
                await asyncio.sleep(0.05)  # Check every 50ms for faster updates

                # Get current price
                price = ticker.last if ticker.last == ticker.last else None
                if price is None:
                    price = ticker.close if ticker.close == ticker.close else None

                if price and price != last_price:
                    now = asyncio.get_event_loop().time()
                    if now - last_broadcast >= 0.05:  # Throttle to 50ms
                        await self._broadcast({
                            'type': 'tick',
                            'symbol': 'ES',
                            'price': price
                        })
                        last_broadcast = now
                        last_price = price

            self.ibkr.ib.cancelMktData(self.ibkr._contract)

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
            await runner.cleanup()
            print("[OK] Shutdown complete")

    def _generate_live_html(self):
        """Generate the live WebSocket-powered dashboard"""
        html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ES/BTC Live Dashboard</title>
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
        .prices {
            display: flex;
            justify-content: center;
            gap: 60px;
            padding: 15px;
            background: #12121a;
        }
        .price-box { text-align: center; }
        .price-label { font-size: 12px; color: #787b86; margin-bottom: 4px; }
        .price-value {
            font-size: 28px;
            font-weight: 600;
            font-family: 'SF Mono', monospace;
            transition: color 0.2s;
        }
        .price-value.up { color: #00C853; }
        .price-value.down { color: #ef5350; }
        .price-change { font-size: 12px; margin-top: 2px; }
        .correlation-bar {
            display: flex;
            justify-content: center;
            gap: 40px;
            padding: 12px;
            background: #0f0f14;
            border-bottom: 1px solid #2a2a3e;
        }
        .corr-item { text-align: center; }
        .corr-label { font-size: 10px; color: #787b86; text-transform: uppercase; }
        .corr-value { font-size: 20px; font-weight: 600; margin-top: 2px; }
        .section-title {
            padding: 12px 20px 8px;
            font-size: 12px;
            color: #787b86;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
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
        .chart-wrapper.historical { height: 240px; }
        .chart-wrapper.correlation { height: 350px; }
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
    </style>
</head>
<body>
    <div class="header">
        <h1>ES / BTC Live Correlation</h1>
        <div class="status">
            <span id="status-text">Connecting...</span>
            <div class="status-dot" id="status-dot"></div>
            <div class="latency">BTC: <span id="btc-rate">0</span>/s | Last: <span id="last-update">--</span></div>
        </div>
    </div>

    <div class="prices">
        <div class="price-box">
            <div class="price-label">ES <span id="es-contract">---</span></div>
            <div class="price-value" id="es-price">---</div>
            <div class="price-change" id="es-change">---</div>
        </div>
        <div class="price-box">
            <div class="price-label">BTC/USDT</div>
            <div class="price-value" id="btc-price">---</div>
            <div class="price-change" id="btc-change">---</div>
        </div>
    </div>

    <div class="correlation-bar">
        <div class="corr-item">
            <div class="corr-label">1 Min</div>
            <div class="corr-value" id="corr-1m" style="color: #787b86">--</div>
        </div>
        <div class="corr-item">
            <div class="corr-label">5 Min</div>
            <div class="corr-value" id="corr-5m" style="color: #787b86">--</div>
        </div>
        <div class="corr-item">
            <div class="corr-label">15 Min</div>
            <div class="corr-value" id="corr-15m" style="color: #787b86">--</div>
        </div>
        <div class="corr-item">
            <div class="corr-label">1 Hour</div>
            <div class="corr-value" id="corr-1h" style="color: #787b86">--</div>
        </div>
    </div>

    <div class="measurement" id="measurement" style="display:none; position:fixed; background:#1a1a2e; padding:8px 12px; border-radius:4px; font-size:12px; z-index:1000; pointer-events:none;">
        <div>Time: <span id="m-time">--</span></div>
        <div>Price: <span id="m-price">--</span></div>
        <div style="color:#787b86">Move: <span id="m-move" style="color:#00C853">--</span></div>
    </div>
    <div class="section-title">Real-Time (1 Min Candles)</div>
    <div class="charts-container">
        <div class="chart-wrapper" id="es-realtime"></div>
        <div class="chart-wrapper" id="btc-realtime"></div>
    </div>

    <div class="section-title">Historical (7 Days - 1 Hour)</div>
    <div class="charts-container">
        <div class="chart-wrapper historical" id="es-historical"></div>
        <div class="chart-wrapper historical" id="btc-historical"></div>
    </div>

    <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background: #00C853"></div> Strong (&gt;0.7)</div>
        <div class="legend-item"><div class="legend-dot" style="background: #FFD600"></div> Moderate (0.4-0.7)</div>
        <div class="legend-item"><div class="legend-dot" style="background: #FF9100"></div> Weak (0.2-0.4)</div>
        <div class="legend-item"><div class="legend-dot" style="background: #FF1744"></div> Divergence (&lt;0.2)</div>
    </div>

    <div class="section-title">Visual Correlation - ES & BTC Overlay (3 Days)</div>
    <div style="background: #0a0a0f; position: relative;">
        <div class="correlation-legend">
            <div class="item"><div class="dot" style="background: #26a69a"></div> ES (% Change)</div>
            <div class="item"><div class="dot" style="background: #FF9800"></div> BTC (% Change)</div>
        </div>
        <div class="chart-wrapper correlation" id="correlation-chart"></div>
        <div class="chart-wrapper" id="volume-chart" style="height: 100px;"></div>
    </div>

    <script>
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

        // Candlestick series
        const esRtSeries = esRtChart.addCandlestickSeries({
            upColor: '#26a69a', downColor: '#ef5350',
            borderUpColor: '#26a69a', borderDownColor: '#ef5350',
            wickUpColor: '#26a69a', wickDownColor: '#ef5350'
        });
        const btcRtSeries = btcRtChart.addCandlestickSeries({
            upColor: '#FF9800', downColor: '#F44336',
            borderUpColor: '#FF9800', borderDownColor: '#F44336',
            wickUpColor: '#FF9800', wickDownColor: '#F44336'
        });
        const esHistSeries = esHistChart.addCandlestickSeries({
            upColor: '#26a69a', downColor: '#ef5350',
            borderUpColor: '#26a69a', borderDownColor: '#ef5350',
            wickUpColor: '#26a69a', wickDownColor: '#ef5350'
        });
        const btcHistSeries = btcHistChart.addCandlestickSeries({
            upColor: '#FF9800', downColor: '#F44336',
            borderUpColor: '#FF9800', borderDownColor: '#F44336',
            wickUpColor: '#FF9800', wickDownColor: '#F44336'
        });

        // Correlation overlay chart (3 days)
        const corrChart = LightweightCharts.createChart(document.getElementById('correlation-chart'),
            { ...chartOptions, width: document.getElementById('correlation-chart').offsetWidth, height: 350 });
        const volumeChart = LightweightCharts.createChart(document.getElementById('volume-chart'),
            { ...chartOptions, width: document.getElementById('volume-chart').offsetWidth, height: 100,
              rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0 } } });

        // ES line series (green) - percentage change
        const esCorrSeries = corrChart.addLineSeries({
            color: '#26a69a',
            lineWidth: 2,
            priceFormat: { type: 'percent' },
            title: 'ES %'
        });

        // BTC line series (orange) - percentage change
        const btcCorrSeries = corrChart.addLineSeries({
            color: '#FF9800',
            lineWidth: 2,
            priceFormat: { type: 'percent' },
            title: 'BTC %'
        });

        // Volume histograms
        const esVolSeries = volumeChart.addHistogramSeries({
            color: '#26a69a',
            priceFormat: { type: 'volume' },
            priceScaleId: 'left'
        });
        const btcVolSeries = volumeChart.addHistogramSeries({
            color: '#FF9800',
            priceFormat: { type: 'volume' },
            priceScaleId: 'right'
        });
        volumeChart.priceScale('left').applyOptions({ scaleMargins: { top: 0, bottom: 0 } });
        volumeChart.priceScale('right').applyOptions({ scaleMargins: { top: 0, bottom: 0 } });

        // Sync time scales between correlation and volume charts
        corrChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (range) volumeChart.timeScale().setVisibleLogicalRange(range);
        });
        volumeChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (range) corrChart.timeScale().setVisibleLogicalRange(range);
        });

        // Measurement state
        let measureStart = null;
        const measureEl = document.getElementById('measurement');

        // Sync crosshairs between paired charts with measurement
        function syncCharts(chart1, series1, chart2, series2, label) {
            chart1.subscribeCrosshairMove(param => {
                if (param.time) {
                    const data = param.seriesData.get(series1);
                    if (data) {
                        chart2.setCrosshairPosition(data, param.time, series2);

                        // Show measurement tooltip
                        const time = new Date(param.time * 1000);
                        document.getElementById('m-time').textContent = time.toLocaleTimeString();
                        document.getElementById('m-price').textContent = data.close ? data.close.toFixed(2) : '--';

                        // Calculate move from start of visible range
                        if (measureStart === null) measureStart = { time: param.time, price: data.close };
                        const priceDiff = data.close - measureStart.price;
                        const pctMove = ((priceDiff / measureStart.price) * 100).toFixed(3);
                        const timeDiff = Math.round((param.time - measureStart.time) / 60);
                        const sign = priceDiff >= 0 ? '+' : '';
                        document.getElementById('m-move').textContent = `${sign}${priceDiff.toFixed(2)} (${sign}${pctMove}%) / ${timeDiff}min`;
                        document.getElementById('m-move').style.color = priceDiff >= 0 ? '#00C853' : '#ef5350';

                        measureEl.style.display = 'block';
                        measureEl.style.left = (param.point.x + 20) + 'px';
                        measureEl.style.top = (param.point.y + 20) + 'px';
                    }
                } else {
                    chart2.clearCrosshairPosition();
                    measureEl.style.display = 'none';
                    measureStart = null;
                }
            });
        }
        // Sync real-time charts
        syncCharts(esRtChart, esRtSeries, btcRtChart, btcRtSeries, 'ES');
        syncCharts(btcRtChart, btcRtSeries, esRtChart, esRtSeries, 'BTC');
        // Sync historical charts
        syncCharts(esHistChart, esHistSeries, btcHistChart, btcHistSeries, 'ES');
        syncCharts(btcHistChart, btcHistSeries, esHistChart, esHistSeries, 'BTC');

        // Data storage for all timeframes
        let esData = [];
        let btcData = [];
        let esHistData = [];
        let btcHistData = [];
        let esCorrData = [];
        let btcCorrData = [];
        let lastEsPrice = null;
        let lastBtcPrice = null;
        let tickCount = 0;
        let lastTickTime = Date.now();

        // Update rate counter every second
        setInterval(() => {
            const now = Date.now();
            const elapsed = (now - lastTickTime) / 1000;
            const rate = Math.round(tickCount / elapsed);
            document.getElementById('btc-rate').textContent = rate;
            tickCount = 0;
            lastTickTime = now;
        }, 1000);

        // Price update with animation
        function updatePrice(element, price, lastPrice) {
            element.textContent = price.toFixed(2);
            element.classList.remove('up', 'down');
            if (lastPrice !== null) {
                element.classList.add(price >= lastPrice ? 'up' : 'down');
            }
            // Update last update time
            const now = new Date();
            document.getElementById('last-update').textContent =
                now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');
        }

        // WebSocket connection
        function connect() {
            const ws = new WebSocket('ws://' + window.location.host + '/ws');

            ws.onopen = () => {
                document.getElementById('status-text').textContent = 'Live';
                document.getElementById('status-dot').classList.add('connected');
            };

            ws.onclose = () => {
                document.getElementById('status-text').textContent = 'Disconnected';
                document.getElementById('status-dot').classList.remove('connected');
                setTimeout(connect, 2000);
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);

                if (msg.type === 'init') {
                    // Set contract
                    document.getElementById('es-contract').textContent = msg.es_contract;

                    // Load backfill data
                    if (msg.es_backfill && msg.es_backfill.length) {
                        esData = msg.es_backfill;
                        esRtSeries.setData(esData);
                        lastEsPrice = esData[esData.length - 1].close;
                        updatePrice(document.getElementById('es-price'), lastEsPrice, null);
                    }
                    if (msg.btc_backfill && msg.btc_backfill.length) {
                        btcData = msg.btc_backfill;
                        btcRtSeries.setData(btcData);
                        lastBtcPrice = btcData[btcData.length - 1].close;
                        updatePrice(document.getElementById('btc-price'), lastBtcPrice, null);
                    }

                    // Load historical and store for live updates
                    if (msg.es_historical && msg.es_historical.length) {
                        esHistData = msg.es_historical;
                        esHistSeries.setData(esHistData);
                    }
                    if (msg.btc_historical && msg.btc_historical.length) {
                        btcHistData = msg.btc_historical;
                        btcHistSeries.setData(btcHistData);
                    }

                    // Populate correlation overlay chart (uses historical hourly data - 3 days = 72 hours)
                    updateCorrelationChart(esHistData, btcHistData);
                }
                else if (msg.type === 'bar') {
                    const bar = msg.data;
                    if (msg.symbol === 'ES') {
                        esRtSeries.update(bar);
                        updatePrice(document.getElementById('es-price'), bar.close, lastEsPrice);
                        lastEsPrice = bar.close;
                        esData.push(bar);
                        if (esData.length > 1440) esData.shift();
                    } else if (msg.symbol === 'BTC') {
                        btcRtSeries.update(bar);
                        updatePrice(document.getElementById('btc-price'), bar.close, lastBtcPrice);
                        lastBtcPrice = bar.close;
                        btcData.push(bar);
                        if (btcData.length > 1440) btcData.shift();
                    }

                    // Update correlation if we have enough data
                    if (esData.length >= 10 && btcData.length >= 10) {
                        updateCorrelation();
                    }
                }
                else if (msg.type === 'tick') {
                    // Live tick updates - update header, real-time chart, AND historical chart
                    tickCount++;
                    if (msg.symbol === 'BTC') {
                        updatePrice(document.getElementById('btc-price'), msg.price, lastBtcPrice);
                        lastBtcPrice = msg.price;
                        // Update real-time chart's current candle
                        if (btcData.length > 0) {
                            const lastBar = btcData[btcData.length - 1];
                            lastBar.close = msg.price;
                            lastBar.high = Math.max(lastBar.high, msg.price);
                            lastBar.low = Math.min(lastBar.low, msg.price);
                            btcRtSeries.update(lastBar);
                        }
                        // Update historical chart's latest candle too
                        if (btcHistData.length > 0) {
                            const lastHistBar = btcHistData[btcHistData.length - 1];
                            lastHistBar.close = msg.price;
                            lastHistBar.high = Math.max(lastHistBar.high, msg.price);
                            lastHistBar.low = Math.min(lastHistBar.low, msg.price);
                            btcHistSeries.update(lastHistBar);
                        }
                        // Update correlation chart with latest BTC price
                        updateCorrChartTick('BTC', msg.price);
                    } else if (msg.symbol === 'ES') {
                        updatePrice(document.getElementById('es-price'), msg.price, lastEsPrice);
                        lastEsPrice = msg.price;
                        // Update real-time chart's current candle
                        if (esData.length > 0) {
                            const lastBar = esData[esData.length - 1];
                            lastBar.close = msg.price;
                            lastBar.high = Math.max(lastBar.high, msg.price);
                            lastBar.low = Math.min(lastBar.low, msg.price);
                            esRtSeries.update(lastBar);
                        }
                        // Update historical chart's latest candle too
                        if (esHistData.length > 0) {
                            const lastHistBar = esHistData[esHistData.length - 1];
                            lastHistBar.close = msg.price;
                            lastHistBar.high = Math.max(lastHistBar.high, msg.price);
                            lastHistBar.low = Math.min(lastHistBar.low, msg.price);
                            esHistSeries.update(lastHistBar);
                        }
                        // Update correlation chart with latest ES price
                        updateCorrChartTick('ES', msg.price);
                    }
                    // Update correlation chart periodically (every 10 ticks to reduce load)
                    if (tickCount % 10 === 0) {
                        updateCorrelationChartLive();
                    }
                }
            };
        }

        // Store base prices for correlation normalization
        let esCorrBase = null;
        let btcCorrBase = null;

        // Update correlation chart line with single tick
        function updateCorrChartTick(symbol, price) {
            if (!esCorrBase || !btcCorrBase) return;

            const now = Math.floor(Date.now() / 1000);
            if (symbol === 'ES') {
                const pctChange = ((price - esCorrBase) / esCorrBase) * 100;
                esCorrSeries.update({ time: now, value: pctChange });
            } else if (symbol === 'BTC') {
                const pctChange = ((price - btcCorrBase) / btcCorrBase) * 100;
                btcCorrSeries.update({ time: now, value: pctChange });
            }
        }

        // Recalculate full correlation chart with live prices
        function updateCorrelationChartLive() {
            if (esHistData.length < 10 || btcHistData.length < 10) return;
            // Just update the last point with current prices
            if (lastEsPrice && lastBtcPrice && esCorrBase && btcCorrBase) {
                const now = Math.floor(Date.now() / 1000);
                esCorrSeries.update({ time: now, value: ((lastEsPrice - esCorrBase) / esCorrBase) * 100 });
                btcCorrSeries.update({ time: now, value: ((lastBtcPrice - btcCorrBase) / btcCorrBase) * 100 });
            }
        }

        // Update correlation overlay chart with normalized % change data
        function updateCorrelationChart(esHist, btcHist) {
            if (!esHist || !btcHist || esHist.length < 10 || btcHist.length < 10) return;

            // Use last 72 hours (3 days) - data is hourly
            const esLast72 = esHist.slice(-72);
            const btcLast72 = btcHist.slice(-72);

            // Find common timestamps
            const esMap = new Map(esLast72.map(d => [d.time, d]));
            const btcMap = new Map(btcLast72.map(d => [d.time, d]));
            const commonTimes = [...esMap.keys()].filter(t => btcMap.has(t)).sort((a, b) => a - b);

            if (commonTimes.length < 5) return;

            // Get base prices for normalization (first common bar) and store globally
            const esBase = esMap.get(commonTimes[0]).close;
            const btcBase = btcMap.get(commonTimes[0]).close;
            esCorrBase = esBase;
            btcCorrBase = btcBase;

            // Calculate % change from base for each
            const esNorm = commonTimes.map(t => ({
                time: t,
                value: ((esMap.get(t).close - esBase) / esBase) * 100
            }));
            const btcNorm = commonTimes.map(t => ({
                time: t,
                value: ((btcMap.get(t).close - btcBase) / btcBase) * 100
            }));

            // Volume data with color based on direction
            const esVol = commonTimes.map(t => {
                const d = esMap.get(t);
                return { time: t, value: d.volume, color: d.close >= d.open ? '#26a69a80' : '#ef535080' };
            });
            const btcVol = commonTimes.map(t => {
                const d = btcMap.get(t);
                return { time: t, value: d.volume / 1000, color: d.close >= d.open ? '#FF980080' : '#F4433680' };
            });

            // Set data
            esCorrSeries.setData(esNorm);
            btcCorrSeries.setData(btcNorm);
            esVolSeries.setData(esVol);
            btcVolSeries.setData(btcVol);

            // Fit to data
            corrChart.timeScale().fitContent();
            volumeChart.timeScale().fitContent();
        }

        // Calculate correlation
        function updateCorrelation() {
            const esReturns = [];
            const btcReturns = [];
            const len = Math.min(esData.length, btcData.length);

            for (let i = 1; i < len; i++) {
                esReturns.push((esData[i].close - esData[i-1].close) / esData[i-1].close);
                btcReturns.push((btcData[i].close - btcData[i-1].close) / btcData[i-1].close);
            }

            if (esReturns.length < 5) return;

            // Pearson correlation
            const n = esReturns.length;
            const sumX = esReturns.reduce((a, b) => a + b, 0);
            const sumY = btcReturns.reduce((a, b) => a + b, 0);
            const sumXY = esReturns.reduce((total, x, i) => total + x * btcReturns[i], 0);
            const sumX2 = esReturns.reduce((total, x) => total + x * x, 0);
            const sumY2 = btcReturns.reduce((total, y) => total + y * y, 0);

            const corr = (n * sumXY - sumX * sumY) /
                Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY));

            // Color based on strength
            let color = '#FF1744';
            if (Math.abs(corr) > 0.7) color = '#00C853';
            else if (Math.abs(corr) > 0.4) color = '#FFD600';
            else if (Math.abs(corr) > 0.2) color = '#FF9100';

            document.getElementById('corr-1m').textContent = corr.toFixed(2);
            document.getElementById('corr-1m').style.color = color;
        }

        // Resize handler
        window.addEventListener('resize', () => {
            esRtChart.applyOptions({ width: document.getElementById('es-realtime').offsetWidth });
            btcRtChart.applyOptions({ width: document.getElementById('btc-realtime').offsetWidth });
            esHistChart.applyOptions({ width: document.getElementById('es-historical').offsetWidth });
            btcHistChart.applyOptions({ width: document.getElementById('btc-historical').offsetWidth });
            corrChart.applyOptions({ width: document.getElementById('correlation-chart').offsetWidth });
            volumeChart.applyOptions({ width: document.getElementById('volume-chart').offsetWidth });
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

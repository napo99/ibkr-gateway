"""
Correlation Dashboard - Main Entry Point
Streams ES from IBKR + BTC from Binance, generates live dashboard

Usage:
    py run_dashboard.py                    # Run with defaults (30 min)
    py run_dashboard.py --duration 60      # Run for 60 minutes
    py run_dashboard.py --refresh 30       # Update HTML every 30 seconds
"""

import asyncio
import argparse
import signal
import sys
import os
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from data_sources import IBKRClient, BinanceClient, OHLCV
from analysis import MultiTimeframeAnalysis, calculate_correlation
from dashboard import DashboardGenerator


class CorrelationDashboard:
    """Main orchestrator for ES/BTC correlation dashboard"""

    def __init__(self, duration_min: int = 30, refresh_sec: int = 60):
        self.duration_min = duration_min
        self.refresh_sec = refresh_sec
        self.running = False

        # Clients
        self.ibkr = IBKRClient(symbol='ES', on_bar=self._on_es_bar)
        self.binance = BinanceClient(on_bar=self._on_btc_bar)

        # Dashboard
        self.dashboard = DashboardGenerator(
            output_path='output/dashboard.html',
            refresh_interval=refresh_sec
        )

        # Historical data cache
        self.es_historical = []
        self.btc_historical = []

        # Signal handling
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print("\n[STOP] Shutting down...")
        self.running = False

    def _on_es_bar(self, bar: OHLCV):
        """Callback when new ES bar arrives"""
        print(f"[ES] {bar.timestamp.strftime('%H:%M')} Close: {bar.close:.2f}")

    def _on_btc_bar(self, bar: OHLCV):
        """Callback when new BTC bar arrives"""
        print(f"[BTC] {bar.timestamp.strftime('%H:%M')} Close: {bar.close:.2f}")

    async def _fetch_historical(self):
        """Fetch 7-day historical data from both sources"""
        print("[INIT] Fetching historical data...")

        # BTC historical (async)
        btc_df = await self.binance.fetch_historical('1h', 168)  # 7 days
        if not btc_df.empty:
            self.btc_historical = [
                {'time': int(row['timestamp'].timestamp()),
                 'open': row['open'], 'high': row['high'],
                 'low': row['low'], 'close': row['close'],
                 'volume': row['volume']}
                for _, row in btc_df.iterrows()
            ]
            print(f"[BTC] Loaded {len(self.btc_historical)} historical bars")

        # ES historical (sync via IBKR)
        es_df = self.ibkr.fetch_historical('7 D', '1 hour')
        if not es_df.empty:
            self.es_historical = [
                {'time': int(row['timestamp'].timestamp()),
                 'open': row['open'], 'high': row['high'],
                 'low': row['low'], 'close': row['close'],
                 'volume': row['volume']}
                for _, row in es_df.iterrows()
            ]
            print(f"[ES] Loaded {len(self.es_historical)} historical bars")

    def _calculate_correlations(self):
        """Calculate multi-timeframe correlations"""
        es_df = self.ibkr.buffer.to_dataframe()
        btc_df = self.binance.buffer.to_dataframe()

        if es_df.empty or btc_df.empty or len(es_df) < 10 or len(btc_df) < 10:
            return {
                '1m': {'correlation': 0, 'color': '#787b86', 'strength': 'N/A'},
                '5m': {'correlation': 0, 'color': '#787b86', 'strength': 'N/A'},
                '15m': {'correlation': 0, 'color': '#787b86', 'strength': 'N/A'},
                '1h': {'correlation': 0, 'color': '#787b86', 'strength': 'N/A'},
            }

        analyzer = MultiTimeframeAnalysis(es_df, btc_df)
        return analyzer.analyze_all()

    def _get_lead_lag_text(self):
        """Generate lead/lag analysis text"""
        es_df = self.ibkr.buffer.to_dataframe()
        btc_df = self.binance.buffer.to_dataframe()

        if es_df.empty or btc_df.empty or len(es_df) < 15:
            return "Collecting data..."

        result = calculate_correlation(
            es_df['close'].values,
            btc_df['close'].values
        )

        if result.lead_lag == 0:
            return "Assets moving in sync"
        elif result.lead_lag > 0:
            return f"ES leads by {result.lead_lag} min (corr: {result.lead_lag_corr:.2f})"
        else:
            return f"BTC leads by {-result.lead_lag} min (corr: {result.lead_lag_corr:.2f})"

    def _update_dashboard(self):
        """Regenerate and save dashboard HTML"""
        es_realtime = self.ibkr.buffer.to_json()
        btc_realtime = self.binance.buffer.to_json()
        correlations = self._calculate_correlations()
        lead_lag = self._get_lead_lag_text()

        html = self.dashboard.generate(
            es_realtime=es_realtime,
            btc_realtime=btc_realtime,
            es_historical=self.es_historical,
            btc_historical=self.btc_historical,
            correlation_results=correlations,
            es_contract=self.ibkr.contract_symbol,
            lead_lag_text=lead_lag
        )
        self.dashboard.save(html)

    async def _run_binance_stream(self):
        """Run Binance WebSocket stream"""
        await self.binance.stream()

    def _run_ibkr_stream(self):
        """Run IBKR stream (blocking)"""
        self.ibkr.stream()

    async def run(self):
        """Main run loop"""
        print("=" * 60)
        print("ES/BTC CORRELATION DASHBOARD")
        print(f"Duration: {self.duration_min} min | Refresh: {self.refresh_sec}s")
        print("=" * 60)

        # Connect to IBKR
        print("\n[INIT] Connecting to IBKR Gateway...")
        if not self.ibkr.connect():
            print("[FAIL] Could not connect to IBKR. Is Gateway running?")
            return

        print(f"[OK] Connected - Contract: {self.ibkr.contract_symbol}")

        # Fetch historical data
        await self._fetch_historical()

        # Create output directory
        os.makedirs('output', exist_ok=True)

        # Initial dashboard
        self._update_dashboard()
        dashboard_path = os.path.abspath('output/dashboard.html')
        print(f"\n[DASHBOARD] Opening: {dashboard_path}")
        webbrowser.open(f'file://{dashboard_path}')

        # Start streaming
        self.running = True
        start_time = datetime.now()

        print(f"\n[STREAM] Starting real-time data collection...")
        print("[STREAM] Press Ctrl+C to stop\n")

        # Run Binance in background
        binance_task = asyncio.create_task(self._run_binance_stream())

        # Run IBKR in thread (it's blocking)
        import threading
        ibkr_thread = threading.Thread(target=self._run_ibkr_stream, daemon=True)
        ibkr_thread.start()

        # Main loop - update dashboard periodically
        last_update = datetime.now()

        try:
            while self.running:
                await asyncio.sleep(1)

                # Check duration
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                if elapsed >= self.duration_min:
                    print(f"\n[INFO] Duration limit ({self.duration_min} min) reached")
                    break

                # Update dashboard periodically
                if (datetime.now() - last_update).total_seconds() >= self.refresh_sec:
                    self._update_dashboard()
                    last_update = datetime.now()
                    print(f"[UPDATE] Dashboard refreshed at {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")

        finally:
            # Cleanup
            self.running = False
            self.binance.stop()
            self.ibkr.disconnect()
            binance_task.cancel()

            # Final update
            self._update_dashboard()
            print("\n[OK] Dashboard saved. View at: output/dashboard.html")
            print("[OK] Shutdown complete")


def main():
    parser = argparse.ArgumentParser(description='ES/BTC Correlation Dashboard')
    parser.add_argument('--duration', type=int, default=30,
                        help='How long to run in minutes (default: 30)')
    parser.add_argument('--refresh', type=int, default=60,
                        help='Dashboard refresh interval in seconds (default: 60)')
    args = parser.parse_args()

    dashboard = CorrelationDashboard(
        duration_min=args.duration,
        refresh_sec=args.refresh
    )

    asyncio.run(dashboard.run())


if __name__ == '__main__':
    main()

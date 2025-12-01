"""
IBKR Streaming Client - Keeps connection open and streams real-time prices

Usage:
    py ibkr_stream.py              # Stream ES and NQ prices
    py ibkr_stream.py --duration 60  # Stream for 60 seconds
    Ctrl+C to stop
"""

from ib_insync import IB, Future, util
from datetime import datetime, timezone
import argparse
import signal
import sys

# Configuration
GATEWAY_HOST = '127.0.0.1'
GATEWAY_PAPER_PORT = 4002
CLIENT_ID = 1


class IBKRStreamer:
    """Streaming IBKR client with live price updates"""

    def __init__(self):
        self.ib = IB()
        self.running = False
        self.tickers = {}

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C"""
        print("\n\n[STOPPING] Received interrupt signal...")
        self.running = False

    def _on_pending_tickers(self, tickers):
        """Called when new price data arrives"""
        utc_now = datetime.now(timezone.utc).strftime('%H:%M:%S')

        for ticker in tickers:
            symbol = ticker.contract.localSymbol
            last = ticker.last if ticker.last == ticker.last else '-'
            bid = ticker.bid if ticker.bid == ticker.bid else '-'
            ask = ticker.ask if ticker.ask == ticker.ask else '-'

            print(f"[{utc_now}] {symbol}: Last={last}, Bid={bid}, Ask={ask}")

    def connect(self):
        """Connect to IBKR Gateway"""
        try:
            print(f"Connecting to IBKR Gateway ({GATEWAY_HOST}:{GATEWAY_PAPER_PORT})...")
            self.ib.connect(GATEWAY_HOST, GATEWAY_PAPER_PORT, clientId=CLIENT_ID)
            print("[OK] Connected!")
            return True
        except Exception as e:
            print(f"[FAIL] Connection error: {e}")
            return False

    def disconnect(self):
        """Clean disconnect"""
        # Cancel all market data subscriptions
        for contract in self.tickers:
            try:
                self.ib.cancelMktData(contract)
            except:
                pass

        self.ib.disconnect()
        print("[OK] Disconnected cleanly")

    def get_front_month(self, symbol):
        """Get front month futures contract"""
        base = Future(symbol, exchange='CME')
        contracts = self.ib.reqContractDetails(base)
        if contracts:
            contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
            return contracts[0].contract
        return None

    def stream(self, symbols=['ES', 'NQ'], duration=None):
        """
        Stream real-time prices

        Args:
            symbols: List of futures symbols to stream
            duration: How long to stream (seconds). None = forever until Ctrl+C
        """
        if not self.connect():
            return

        try:
            # Get contracts
            contracts = []
            for sym in symbols:
                contract = self.get_front_month(sym)
                if contract:
                    contracts.append(contract)
                    print(f"  {sym}: {contract.localSymbol} (expires {contract.lastTradeDateOrContractMonth})")
                else:
                    print(f"  {sym}: Could not find contract")

            if not contracts:
                print("[FAIL] No contracts found")
                return

            # Request streaming market data
            print("\n" + "=" * 60)
            print("STREAMING PRICES (Ctrl+C to stop)")
            print("=" * 60 + "\n")

            # Subscribe to market data with callback
            self.ib.reqMarketDataType(3)  # Delayed data

            for contract in contracts:
                ticker = self.ib.reqMktData(contract, '', False, False)
                self.tickers[contract] = ticker

            # Set up callback for price updates
            self.ib.pendingTickersEvent += self._on_pending_tickers

            # Keep running
            self.running = True
            start_time = datetime.now()

            while self.running:
                self.ib.sleep(1)  # Process events every second

                # Check duration limit
                if duration:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= duration:
                        print(f"\n[INFO] Duration limit ({duration}s) reached")
                        break

        except Exception as e:
            print(f"[ERROR] {e}")

        finally:
            self.disconnect()


def main():
    parser = argparse.ArgumentParser(description='IBKR Price Streamer')
    parser.add_argument('--duration', type=int, default=30,
                        help='How long to stream in seconds (default: 30)')
    parser.add_argument('--symbols', nargs='+', default=['ES', 'NQ'],
                        help='Symbols to stream (default: ES NQ)')
    args = parser.parse_args()

    print("=" * 60)
    print(f"IBKR PRICE STREAMER")
    print(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")

    streamer = IBKRStreamer()
    streamer.stream(symbols=args.symbols, duration=args.duration)


if __name__ == '__main__':
    main()

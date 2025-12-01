"""
IBKR Client - Single properly managed connection
Based on ib_insync best practices

Usage:
    py ibkr_client.py              # Test connection and get ES/NQ prices
    py ibkr_client.py --live       # Request live data (type 1)
    py ibkr_client.py --delayed    # Request delayed data (type 3)
"""

from ib_insync import IB, Future, Stock, util
from datetime import datetime, timezone
from contextlib import contextmanager
import argparse
import sys

# Configuration
GATEWAY_HOST = '127.0.0.1'
GATEWAY_PAPER_PORT = 4002
GATEWAY_LIVE_PORT = 4001
CLIENT_ID = 1  # Always use same client ID


class IBKRClient:
    """Properly managed IBKR connection"""

    def __init__(self, host=GATEWAY_HOST, port=GATEWAY_PAPER_PORT, client_id=CLIENT_ID):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self._connected = False

        # Set up error handling
        self.ib.errorEvent += self._on_error
        self.errors = []

    def _on_error(self, reqId, errorCode, errorString, contract):
        """Handle errors from IBKR"""
        # Ignore informational messages (codes 2104, 2106, 2158)
        if errorCode in [2104, 2106, 2158]:
            return

        error_msg = f"[{errorCode}] {errorString}"
        if contract:
            error_msg += f" (Contract: {contract.symbol})"
        self.errors.append(error_msg)

        # Print critical errors immediately
        if errorCode not in [321, 2104, 2106, 2158]:  # Skip read-only warnings
            print(f"  ERROR: {error_msg}")

    def connect(self):
        """Connect to IBKR Gateway"""
        if self._connected:
            return True

        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
            return True
        except ConnectionRefusedError:
            print(f"[FAIL] Cannot connect to {self.host}:{self.port}")
            print("  - Is IB Gateway running?")
            print("  - Is API enabled in Gateway settings?")
            return False
        except Exception as e:
            print(f"[FAIL] Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from IBKR Gateway"""
        if self._connected:
            self.ib.disconnect()
            self._connected = False

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - always disconnect"""
        self.disconnect()
        return False

    def get_front_month_future(self, symbol='ES'):
        """Get front month futures contract"""
        if not self._connected:
            return None

        base = Future(symbol, exchange='CME')
        contracts = self.ib.reqContractDetails(base)

        if not contracts:
            return None

        contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
        return contracts[0].contract

    def get_market_data(self, contract, data_type=3, timeout=5):
        """
        Get market data for a contract

        data_type:
            1 = Live (requires subscription)
            2 = Frozen (last available)
            3 = Delayed (15-20 min delay, free)
            4 = Delayed Frozen
        """
        if not self._connected:
            return None

        self.ib.reqMarketDataType(data_type)
        ticker = self.ib.reqMktData(contract, '', False, False)
        self.ib.sleep(timeout)
        self.ib.cancelMktData(contract)

        return {
            'symbol': contract.localSymbol,
            'last': ticker.last if ticker.last == ticker.last else None,
            'bid': ticker.bid if ticker.bid == ticker.bid else None,
            'ask': ticker.ask if ticker.ask == ticker.ask else None,
            'high': ticker.high if ticker.high == ticker.high else None,
            'low': ticker.low if ticker.low == ticker.low else None,
            'open': ticker.open if ticker.open == ticker.open else None,
            'close': ticker.close if ticker.close == ticker.close else None,
            'volume': ticker.volume if ticker.volume == ticker.volume else None,
        }

    def get_historical_data(self, contract, duration='1 D', bar_size='1 hour'):
        """Get historical OHLCV data"""
        if not self._connected:
            return None

        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )

        return bars

    def get_account_info(self):
        """Get account information"""
        if not self._connected:
            return None

        return {
            'accounts': self.ib.managedAccounts(),
            'server_time': self.ib.reqCurrentTime()
        }


def main():
    parser = argparse.ArgumentParser(description='IBKR Client Test')
    parser.add_argument('--live', action='store_true', help='Request live data')
    parser.add_argument('--delayed', action='store_true', help='Request delayed data')
    args = parser.parse_args()

    data_type = 1 if args.live else 3  # Default to delayed

    utc_now = datetime.now(timezone.utc)
    print("=" * 60)
    print(f"IBKR CLIENT - {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)

    # Use context manager for proper connection handling
    with IBKRClient() as client:
        if not client._connected:
            print("\n[FAIL] Could not connect to IBKR Gateway")
            return 1

        print("[OK] Connected to IBKR Gateway")

        # Account info
        info = client.get_account_info()
        if info:
            print(f"\nAccount: {info['accounts']}")
            print(f"Server Time: {info['server_time']}")

        # Get ES front month
        print("\n" + "-" * 60)
        print("ES Futures (E-mini S&P 500)")
        print("-" * 60)

        es = client.get_front_month_future('ES')
        if es:
            print(f"Contract: {es.localSymbol} (expires {es.lastTradeDateOrContractMonth})")

            # Market data
            data = client.get_market_data(es, data_type=data_type)
            if data:
                print(f"  Last:  {data['last'] or 'N/A'}")
                print(f"  Bid:   {data['bid'] or 'N/A'}")
                print(f"  Ask:   {data['ask'] or 'N/A'}")
                print(f"  Close: {data['close'] or 'N/A'}")

            # Historical data as fallback
            if not data['last']:
                print("\nTrying historical data...")
                bars = client.get_historical_data(es)
                if bars:
                    last_bar = bars[-1]
                    print(f"  Last bar: {last_bar.date}")
                    print(f"  Close:    {last_bar.close}")
                else:
                    print("  No historical data available")
        else:
            print("  Could not get ES contract")

        # Get NQ front month
        print("\n" + "-" * 60)
        print("NQ Futures (E-mini NASDAQ 100)")
        print("-" * 60)

        nq = client.get_front_month_future('NQ')
        if nq:
            print(f"Contract: {nq.localSymbol} (expires {nq.lastTradeDateOrContractMonth})")

            data = client.get_market_data(nq, data_type=data_type)
            if data:
                print(f"  Last:  {data['last'] or 'N/A'}")
                print(f"  Bid:   {data['bid'] or 'N/A'}")
                print(f"  Ask:   {data['ask'] or 'N/A'}")
                print(f"  Close: {data['close'] or 'N/A'}")
        else:
            print("  Could not get NQ contract")

        # Show errors if any
        if client.errors:
            print("\n" + "-" * 60)
            print("Errors encountered:")
            for err in client.errors:
                print(f"  {err}")

        print("\n" + "=" * 60)
        print("[OK] Disconnected cleanly")

    return 0


if __name__ == '__main__':
    sys.exit(main())

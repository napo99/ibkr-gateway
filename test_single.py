"""
Single clean connection test - ONE connection only
"""

from ib_insync import IB, Stock, Future
from datetime import datetime, timezone
import sys

def main():
    ib = IB()

    utc_now = datetime.now(timezone.utc)
    print("=" * 60)
    print(f"SINGLE CONNECTION TEST")
    print(f"UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        # ONE connection with client ID 1
        print("\nConnecting with clientId=1...")
        ib.connect('127.0.0.1', 4002, clientId=1)
        print("[OK] Connected!")

        # Request delayed data
        print("\nRequesting delayed market data (type 3)...")
        ib.reqMarketDataType(3)

        # Test ES
        print("\n--- ES Futures ---")
        es = Future('ES', '20251219', 'CME')
        ib.qualifyContracts(es)
        print(f"Contract: {es.localSymbol}")

        es_ticker = ib.reqMktData(es, '', False, False)
        ib.sleep(5)

        print(f"  Last:  {es_ticker.last}")
        print(f"  Bid:   {es_ticker.bid}")
        print(f"  Ask:   {es_ticker.ask}")
        print(f"  Close: {es_ticker.close}")

        ib.cancelMktData(es)

        # Test historical as backup
        print("\n--- Historical Data ---")
        bars = ib.reqHistoricalData(
            es,
            endDateTime='',
            durationStr='1 D',
            barSizeSetting='1 hour',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )

        if bars:
            print(f"Got {len(bars)} historical bars")
            print(f"Last bar: {bars[-1].date} - Close: {bars[-1].close}")
        else:
            print("No historical data")

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        # ALWAYS disconnect
        print("\n--- Disconnecting ---")
        ib.disconnect()
        print("[OK] Disconnected cleanly")

if __name__ == '__main__':
    main()

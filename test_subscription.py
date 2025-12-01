"""
Check market data subscription status and try different data types
"""

from ib_insync import IB, Future
from datetime import datetime, timezone

def get_front_month_contract(ib, symbol='ES'):
    base = Future(symbol, exchange='CME')
    contracts = ib.reqContractDetails(base)
    contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
    return contracts[0].contract

def main():
    ib = IB()

    utc_now = datetime.now(timezone.utc)
    print("=" * 70)
    print(f"MARKET DATA SUBSCRIPTION TEST")
    print(f"UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    ib.connect('127.0.0.1', 4002, clientId=6)
    print("[OK] Connected!")

    es = get_front_month_contract(ib, 'ES')
    print(f"\nTesting with: {es.localSymbol}")

    # Try different market data types
    print("\n" + "-" * 70)
    print("Testing different market data types...")
    print("-" * 70)

    # Type 1: Live (requires subscription)
    print("\n[1] LIVE data (Type 1)...")
    ib.reqMarketDataType(1)
    ticker1 = ib.reqMktData(es, '', False, False)
    ib.sleep(3)
    print(f"    Last: {ticker1.last}, Bid: {ticker1.bid}, Ask: {ticker1.ask}")
    ib.cancelMktData(es)

    # Type 2: Frozen (last available)
    print("\n[2] FROZEN data (Type 2)...")
    ib.reqMarketDataType(2)
    ticker2 = ib.reqMktData(es, '', False, False)
    ib.sleep(3)
    print(f"    Last: {ticker2.last}, Bid: {ticker2.bid}, Ask: {ticker2.ask}")
    ib.cancelMktData(es)

    # Type 3: Delayed (15-20 min delay, free)
    print("\n[3] DELAYED data (Type 3)...")
    ib.reqMarketDataType(3)
    ticker3 = ib.reqMktData(es, '', False, False)
    ib.sleep(3)
    print(f"    Last: {ticker3.last}, Bid: {ticker3.bid}, Ask: {ticker3.ask}")
    ib.cancelMktData(es)

    # Type 4: Delayed Frozen
    print("\n[4] DELAYED FROZEN data (Type 4)...")
    ib.reqMarketDataType(4)
    ticker4 = ib.reqMktData(es, '', False, False)
    ib.sleep(3)
    print(f"    Last: {ticker4.last}, Bid: {ticker4.bid}, Ask: {ticker4.ask}")
    ib.cancelMktData(es)

    print("\n" + "=" * 70)
    print("INTERPRETATION:")
    print("=" * 70)
    print("""
    If ALL show 'nan':
      - You may need to subscribe to CME futures market data
      - Paper accounts often need explicit market data subscriptions
      - Go to IBKR Account Management > Settings > Market Data Subscriptions

    If Type 3/4 work but 1/2 don't:
      - You have delayed data but not live data subscription

    CME Futures Market Data (for ES/NQ):
      - "CME E-mini Equity Index Futures" subscription needed
      - Usually ~$10/month for non-professional
    """)

    ib.disconnect()
    print("[OK] Done!")

if __name__ == '__main__':
    main()

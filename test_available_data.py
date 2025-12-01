"""
Test what market data is available with current subscriptions
"""

from ib_insync import IB, Stock, Crypto, Future
from datetime import datetime, timezone

def main():
    ib = IB()

    utc_now = datetime.now(timezone.utc)
    print("=" * 70)
    print(f"TESTING AVAILABLE MARKET DATA")
    print(f"UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    ib.connect('127.0.0.1', 4002, clientId=7)
    print("[OK] Connected!\n")

    # Test SPY (US Equities - should work with US Real-Time)
    print("-" * 70)
    print("TEST 1: SPY (US Equity ETF)")
    print("-" * 70)
    spy = Stock('SPY', 'SMART', 'USD')
    ib.qualifyContracts(spy)

    ib.reqMarketDataType(3)  # Try delayed first
    spy_ticker = ib.reqMktData(spy, '', False, False)
    ib.sleep(3)
    print(f"  SPY Last:  {spy_ticker.last}")
    print(f"  SPY Bid:   {spy_ticker.bid}")
    print(f"  SPY Ask:   {spy_ticker.ask}")
    print(f"  SPY Close: {spy_ticker.close}")
    ib.cancelMktData(spy)

    # Test BTC via PAXOS
    print("\n" + "-" * 70)
    print("TEST 2: BTC (PAXOS Cryptocurrency)")
    print("-" * 70)
    try:
        btc = Crypto('BTC', 'PAXOS', 'USD')
        ib.qualifyContracts(btc)

        btc_ticker = ib.reqMktData(btc, '', False, False)
        ib.sleep(3)
        print(f"  BTC Last:  {btc_ticker.last}")
        print(f"  BTC Bid:   {btc_ticker.bid}")
        print(f"  BTC Ask:   {btc_ticker.ask}")
        print(f"  BTC Close: {btc_ticker.close}")
        ib.cancelMktData(btc)
    except Exception as e:
        print(f"  BTC Error: {e}")

    # Test QQQ (NASDAQ ETF - tracks NQ)
    print("\n" + "-" * 70)
    print("TEST 3: QQQ (NASDAQ 100 ETF - proxy for NQ)")
    print("-" * 70)
    qqq = Stock('QQQ', 'SMART', 'USD')
    ib.qualifyContracts(qqq)

    qqq_ticker = ib.reqMktData(qqq, '', False, False)
    ib.sleep(3)
    print(f"  QQQ Last:  {qqq_ticker.last}")
    print(f"  QQQ Bid:   {qqq_ticker.bid}")
    print(f"  QQQ Ask:   {qqq_ticker.ask}")
    print(f"  QQQ Close: {qqq_ticker.close}")
    ib.cancelMktData(qqq)

    # Test ES Futures one more time
    print("\n" + "-" * 70)
    print("TEST 4: ES Futures (CME - likely won't work)")
    print("-" * 70)
    es = Future('ES', '20251219', 'CME')
    ib.qualifyContracts(es)

    es_ticker = ib.reqMktData(es, '', False, False)
    ib.sleep(3)
    print(f"  ES Last:  {es_ticker.last}")
    print(f"  ES Bid:   {es_ticker.bid}")
    print(f"  ES Ask:   {es_ticker.ask}")
    print(f"  ES Close: {es_ticker.close}")
    ib.cancelMktData(es)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
    If SPY/QQQ work: You can use ETFs as proxies for ES/NQ
    If BTC works: You have crypto data via PAXOS
    If ES fails: You need CME Futures subscription

    Note: ETF markets (SPY/QQQ) are closed right now (pre-market).
    They trade 9:30 AM - 4:00 PM ET (14:30 - 21:00 UTC)
    Pre-market: 4:00 AM - 9:30 AM ET (09:00 - 14:30 UTC)
    """)

    ib.disconnect()
    print("[OK] Done!")

if __name__ == '__main__':
    main()

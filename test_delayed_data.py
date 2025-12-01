"""
Fetch delayed market data for ES and NQ
Delayed data works even without real-time market data subscription
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
    print(f"ES & NQ PRICES (Delayed Data)")
    print(f"UTC Time: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print("\nConnecting to IBKR Gateway...")
    ib.connect('127.0.0.1', 4002, clientId=5)
    print("[OK] Connected!")

    # Get front month contracts
    es = get_front_month_contract(ib, 'ES')
    nq = get_front_month_contract(ib, 'NQ')

    print(f"\nContracts:")
    print(f"  ES: {es.localSymbol}")
    print(f"  NQ: {nq.localSymbol}")

    # Request DELAYED market data (type 3)
    # This should work without real-time data subscription
    print("\nRequesting delayed market data...")
    ib.reqMarketDataType(3)  # 3 = Delayed data

    es_ticker = ib.reqMktData(es, '', False, False)
    nq_ticker = ib.reqMktData(nq, '', False, False)

    # Wait longer for delayed data
    print("Waiting for data (5 seconds)...")
    ib.sleep(5)

    print("\n" + "=" * 70)
    print("PRICES (may be 15-20 min delayed)")
    print("=" * 70)

    # ES Data
    print(f"\n  ES ({es.localSymbol}) - E-mini S&P 500")
    print(f"  {'-'*40}")
    print(f"  Last:    {es_ticker.last if es_ticker.last == es_ticker.last else 'N/A'}")
    print(f"  Bid:     {es_ticker.bid if es_ticker.bid == es_ticker.bid else 'N/A'}")
    print(f"  Ask:     {es_ticker.ask if es_ticker.ask == es_ticker.ask else 'N/A'}")
    print(f"  High:    {es_ticker.high if es_ticker.high == es_ticker.high else 'N/A'}")
    print(f"  Low:     {es_ticker.low if es_ticker.low == es_ticker.low else 'N/A'}")
    print(f"  Open:    {es_ticker.open if es_ticker.open == es_ticker.open else 'N/A'}")
    print(f"  Close:   {es_ticker.close if es_ticker.close == es_ticker.close else 'N/A'}")

    # NQ Data
    print(f"\n  NQ ({nq.localSymbol}) - E-mini NASDAQ 100")
    print(f"  {'-'*40}")
    print(f"  Last:    {nq_ticker.last if nq_ticker.last == nq_ticker.last else 'N/A'}")
    print(f"  Bid:     {nq_ticker.bid if nq_ticker.bid == nq_ticker.bid else 'N/A'}")
    print(f"  Ask:     {nq_ticker.ask if nq_ticker.ask == nq_ticker.ask else 'N/A'}")
    print(f"  High:    {nq_ticker.high if nq_ticker.high == nq_ticker.high else 'N/A'}")
    print(f"  Low:     {nq_ticker.low if nq_ticker.low == nq_ticker.low else 'N/A'}")
    print(f"  Open:    {nq_ticker.open if nq_ticker.open == nq_ticker.open else 'N/A'}")
    print(f"  Close:   {nq_ticker.close if nq_ticker.close == nq_ticker.close else 'N/A'}")

    # Also try snapshot
    print("\n" + "-" * 70)
    print("Trying snapshot request...")

    try:
        es_snapshot = ib.reqMktData(es, '', True, False)  # snapshot=True
        ib.sleep(2)
        print(f"ES Snapshot Last: {es_snapshot.last}")
    except Exception as e:
        print(f"Snapshot error: {e}")

    ib.disconnect()
    print("\n[OK] Done!")

if __name__ == '__main__':
    main()

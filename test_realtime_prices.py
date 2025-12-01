"""
Fetch real-time prices for ES and NQ front month contracts
"""

from ib_insync import IB, Future
from datetime import datetime, timezone

def get_front_month_contract(ib, symbol='ES'):
    """Automatically get front month contract"""
    base = Future(symbol, exchange='CME')
    contracts = ib.reqContractDetails(base)
    contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
    return contracts[0].contract

def main():
    ib = IB()

    print("=" * 70)
    print("REAL-TIME ES & NQ PRICES")
    print("=" * 70)

    # Current UTC time
    utc_now = datetime.now(timezone.utc)
    print(f"UTC Time: {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("-" * 70)

    print("\nConnecting to IBKR Gateway...")
    ib.connect('127.0.0.1', 4002, clientId=3)
    print("[OK] Connected!")

    # Get server time
    server_time = ib.reqCurrentTime()
    print(f"IBKR Server Time: {server_time}")
    print("-" * 70)

    # Get front month contracts
    print("\nFetching front month contracts...")
    es = get_front_month_contract(ib, 'ES')
    nq = get_front_month_contract(ib, 'NQ')

    print(f"  ES: {es.localSymbol} (expires {es.lastTradeDateOrContractMonth})")
    print(f"  NQ: {nq.localSymbol} (expires {nq.lastTradeDateOrContractMonth})")
    print("-" * 70)

    # Request market data
    print("\nRequesting real-time market data...")
    es_ticker = ib.reqMktData(es)
    nq_ticker = ib.reqMktData(nq)

    # Wait for data to arrive
    print("Waiting for data (3 seconds)...")
    ib.sleep(3)

    # Display prices
    print("\n" + "=" * 70)
    print("CURRENT PRICES")
    print("=" * 70)

    print(f"\n{'='*35}")
    print(f"  ES ({es.localSymbol}) - E-mini S&P 500")
    print(f"{'='*35}")
    print(f"  Last:    {es_ticker.last or 'N/A'}")
    print(f"  Bid:     {es_ticker.bid or 'N/A'}")
    print(f"  Ask:     {es_ticker.ask or 'N/A'}")
    print(f"  High:    {es_ticker.high or 'N/A'}")
    print(f"  Low:     {es_ticker.low or 'N/A'}")
    print(f"  Open:    {es_ticker.open or 'N/A'}")
    print(f"  Close:   {es_ticker.close or 'N/A'}")
    print(f"  Volume:  {es_ticker.volume or 'N/A'}")

    print(f"\n{'='*35}")
    print(f"  NQ ({nq.localSymbol}) - E-mini NASDAQ 100")
    print(f"{'='*35}")
    print(f"  Last:    {nq_ticker.last or 'N/A'}")
    print(f"  Bid:     {nq_ticker.bid or 'N/A'}")
    print(f"  Ask:     {nq_ticker.ask or 'N/A'}")
    print(f"  High:    {nq_ticker.high or 'N/A'}")
    print(f"  Low:     {nq_ticker.low or 'N/A'}")
    print(f"  Open:    {nq_ticker.open or 'N/A'}")
    print(f"  Close:   {nq_ticker.close or 'N/A'}")
    print(f"  Volume:  {nq_ticker.volume or 'N/A'}")

    # Cancel market data
    ib.cancelMktData(es)
    ib.cancelMktData(nq)

    ib.disconnect()
    print("\n" + "-" * 70)
    print(f"Data fetched at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("[OK] Done!")

if __name__ == '__main__':
    main()

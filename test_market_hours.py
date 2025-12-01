"""
Check market hours and delayed data for ES/NQ
"""

from ib_insync import IB, Future
from datetime import datetime, timezone

def get_front_month_contract(ib, symbol='ES'):
    base = Future(symbol, exchange='CME')
    contracts = ib.reqContractDetails(base)
    contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
    return contracts[0]  # Return full contract details

def main():
    ib = IB()

    utc_now = datetime.now(timezone.utc)
    print("=" * 70)
    print(f"MARKET HOURS CHECK - {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Day of week: {utc_now.strftime('%A')}")
    print("=" * 70)

    print("\nConnecting to IBKR Gateway...")
    ib.connect('127.0.0.1', 4002, clientId=4)
    print("[OK] Connected!")

    # Get contract details (includes trading hours)
    print("\nFetching contract details...")
    es_details = get_front_month_contract(ib, 'ES')

    print(f"\nES Contract: {es_details.contract.localSymbol}")
    print(f"Trading Hours: {es_details.tradingHours[:200]}...")  # First 200 chars
    print(f"Liquid Hours:  {es_details.liquidHours[:200]}...")

    # ES/NQ Trading Schedule:
    print("\n" + "=" * 70)
    print("ES/NQ FUTURES TRADING SCHEDULE (CME Globex)")
    print("=" * 70)
    print("""
    Sunday:    6:00 PM - Friday 5:00 PM ET (continuous)

    Daily Break: 5:00 PM - 6:00 PM ET (maintenance)

    Weekend Closed: Friday 5:00 PM - Sunday 6:00 PM ET

    Current UTC: {utc}

    Market Status: {status}
    """.format(
        utc=utc_now.strftime('%Y-%m-%d %H:%M:%S UTC'),
        status="CLOSED (Weekend)" if utc_now.weekday() >= 5 or (utc_now.weekday() == 6 and utc_now.hour < 23) else "OPEN"
    ))

    # Try to get historical data instead (should work even when closed)
    print("-" * 70)
    print("Trying HISTORICAL data (last available prices)...")
    print("-" * 70)

    es = es_details.contract

    # Request last 5 minutes of 1-min bars
    bars = ib.reqHistoricalData(
        es,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 hour',
        whatToShow='TRADES',
        useRTH=False,  # Include extended hours
        formatDate=1
    )

    if bars:
        print(f"\nLast {min(5, len(bars))} hourly bars for ES:")
        print(f"{'Time (UTC)':<25} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume'}")
        print("-" * 80)
        for bar in bars[-5:]:
            print(f"{str(bar.date):<25} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {bar.volume}")

        last_bar = bars[-1]
        print(f"\n>>> LAST KNOWN ES PRICE: {last_bar.close:.2f}")
        print(f">>> As of: {last_bar.date}")
    else:
        print("No historical data available")

    # Same for NQ
    nq_details = get_front_month_contract(ib, 'NQ')
    nq = nq_details.contract

    bars_nq = ib.reqHistoricalData(
        nq,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 hour',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1
    )

    if bars_nq:
        print(f"\nLast {min(5, len(bars_nq))} hourly bars for NQ:")
        print(f"{'Time (UTC)':<25} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume'}")
        print("-" * 80)
        for bar in bars_nq[-5:]:
            print(f"{str(bar.date):<25} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {bar.volume}")

        last_bar = bars_nq[-1]
        print(f"\n>>> LAST KNOWN NQ PRICE: {last_bar.close:.2f}")
        print(f">>> As of: {last_bar.date}")

    ib.disconnect()
    print("\n[OK] Done!")

if __name__ == '__main__':
    main()

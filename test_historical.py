"""
Test historical data - works even when markets are closed
"""

from ib_insync import IB, Stock, Future
from datetime import datetime, timezone

def main():
    ib = IB()

    utc_now = datetime.now(timezone.utc)
    print("=" * 70)
    print(f"HISTORICAL DATA TEST - {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 70)

    ib.connect('127.0.0.1', 4002, clientId=9)
    print("[OK] Connected!\n")

    # Test SPY historical
    print("-" * 70)
    print("TEST 1: SPY Historical Data (Last 1 Day, Hourly Bars)")
    print("-" * 70)

    spy = Stock('SPY', 'SMART', 'USD')
    ib.qualifyContracts(spy)

    bars = ib.reqHistoricalData(
        spy,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 hour',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1
    )

    if bars:
        print(f"Got {len(bars)} bars!")
        print(f"\n{'Time':<22} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume'}")
        print("-" * 70)
        for bar in bars[-5:]:  # Last 5 bars
            print(f"{str(bar.date):<22} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {bar.volume}")
        print(f"\n>>> LAST SPY PRICE: {bars[-1].close:.2f}")
    else:
        print("No historical data received for SPY")

    # Test ES historical
    print("\n" + "-" * 70)
    print("TEST 2: ES Futures Historical Data")
    print("-" * 70)

    es = Future('ES', '20251219', 'CME')
    ib.qualifyContracts(es)

    es_bars = ib.reqHistoricalData(
        es,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 hour',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1
    )

    if es_bars:
        print(f"Got {len(es_bars)} bars!")
        print(f"\n{'Time':<22} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume'}")
        print("-" * 70)
        for bar in es_bars[-5:]:
            print(f"{str(bar.date):<22} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {bar.volume}")
        print(f"\n>>> LAST ES PRICE: {es_bars[-1].close:.2f}")
    else:
        print("No historical data received for ES")

    # Test NQ historical
    print("\n" + "-" * 70)
    print("TEST 3: NQ Futures Historical Data")
    print("-" * 70)

    nq = Future('NQ', '20251219', 'CME')
    ib.qualifyContracts(nq)

    nq_bars = ib.reqHistoricalData(
        nq,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 hour',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1
    )

    if nq_bars:
        print(f"Got {len(nq_bars)} bars!")
        print(f"\n{'Time':<22} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume'}")
        print("-" * 70)
        for bar in nq_bars[-5:]:
            print(f"{str(bar.date):<22} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {bar.volume}")
        print(f"\n>>> LAST NQ PRICE: {nq_bars[-1].close:.2f}")
    else:
        print("No historical data received for NQ")

    ib.disconnect()
    print("\n" + "=" * 70)
    print("[OK] Done!")

if __name__ == '__main__':
    main()

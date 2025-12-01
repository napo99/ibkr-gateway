"""
Inspect IBKR data structures - what fields are available?
"""

from ib_insync import IB, Future
from datetime import datetime, timezone

GATEWAY_HOST = '127.0.0.1'
GATEWAY_PAPER_PORT = 4002
CLIENT_ID = 1


def main():
    ib = IB()

    print("=" * 70)
    print("IBKR DATA STRUCTURE INSPECTION")
    print("=" * 70)

    ib.connect(GATEWAY_HOST, GATEWAY_PAPER_PORT, clientId=CLIENT_ID)
    print("[OK] Connected\n")

    # Get ES front month
    base = Future('ES', exchange='CME')
    contracts = ib.reqContractDetails(base)
    contracts.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
    es = contracts[0].contract

    print(f"Contract: {es.localSymbol}")
    print("=" * 70)

    # 1. TICK DATA (real-time streaming)
    print("\n[1] TICK DATA (reqMktData) - Real-time streaming")
    print("-" * 70)

    ib.reqMarketDataType(3)
    ticker = ib.reqMktData(es, '', False, False)
    ib.sleep(3)

    print(f"Ticker object type: {type(ticker)}")
    print(f"\nAll ticker attributes:")
    for attr in dir(ticker):
        if not attr.startswith('_'):
            val = getattr(ticker, attr)
            if not callable(val):
                print(f"  {attr}: {val}")

    ib.cancelMktData(es)

    # 2. REAL-TIME BARS (5-second bars)
    print("\n\n[2] REAL-TIME BARS (reqRealTimeBars) - 5-second OHLCV")
    print("-" * 70)
    print("Requesting 5-second bars for 10 seconds...")

    bars_received = []

    def on_bar_update(bars, hasNewBar):
        if hasNewBar:
            bar = bars[-1]
            bars_received.append(bar)
            print(f"  Bar: {bar}")

    realtime_bars = ib.reqRealTimeBars(es, 5, 'TRADES', False)
    realtime_bars.updateEvent += on_bar_update
    ib.sleep(12)
    ib.cancelRealTimeBars(realtime_bars)

    if bars_received:
        print(f"\nBar object type: {type(bars_received[0])}")
        print(f"Bar attributes:")
        bar = bars_received[0]
        for attr in dir(bar):
            if not attr.startswith('_'):
                val = getattr(bar, attr)
                if not callable(val):
                    print(f"  {attr}: {val}")

    # 3. HISTORICAL BARS (any timeframe)
    print("\n\n[3] HISTORICAL BARS (reqHistoricalData) - Custom timeframes")
    print("-" * 70)

    # 1-minute bars
    print("\n1-MINUTE BARS (last 30 minutes):")
    bars_1m = ib.reqHistoricalData(
        es,
        endDateTime='',
        durationStr='1800 S',  # 30 minutes
        barSizeSetting='1 min',
        whatToShow='TRADES',
        useRTH=False,
        formatDate=1
    )

    if bars_1m:
        print(f"  Received {len(bars_1m)} bars")
        print(f"  Bar type: {type(bars_1m[0])}")
        print(f"\n  Sample bar attributes:")
        bar = bars_1m[-1]
        for attr in dir(bar):
            if not attr.startswith('_'):
                val = getattr(bar, attr)
                if not callable(val):
                    print(f"    {attr}: {val}")

        print(f"\n  Last 5 bars:")
        print(f"  {'Time':<20} {'Open':<10} {'High':<10} {'Low':<10} {'Close':<10} {'Volume':<10}")
        print(f"  {'-'*70}")
        for bar in bars_1m[-5:]:
            print(f"  {str(bar.date):<20} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {bar.volume:<10}")

    # Available bar sizes
    print("\n\n[4] AVAILABLE BAR SIZES")
    print("-" * 70)
    print("""
    Historical bar sizes supported by IBKR:
    - '1 secs'    (max 1800 seconds of data)
    - '5 secs'    (max 7200 seconds)
    - '10 secs'
    - '15 secs'
    - '30 secs'
    - '1 min'     (max 1 day)
    - '2 mins'
    - '3 mins'
    - '5 mins'    (max 1 week)
    - '10 mins'
    - '15 mins'
    - '20 mins'
    - '30 mins'
    - '1 hour'    (max 1 month)
    - '2 hours'
    - '3 hours'
    - '4 hours'
    - '8 hours'
    - '1 day'     (max 1 year)
    - '1 week'
    - '1 month'
    """)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY: DATA TYPES AVAILABLE")
    print("=" * 70)
    print("""
    1. TICK DATA (reqMktData):
       - Real-time bid/ask/last/volume
       - Updates on every tick (sub-second)
       - No timestamp per tick (you add your own)
       - Fields: last, bid, ask, bidSize, askSize, volume, high, low, open, close

    2. REAL-TIME BARS (reqRealTimeBars):
       - 5-second OHLCV bars ONLY
       - Includes timestamp
       - Fields: time, open, high, low, close, volume, wap, count

    3. HISTORICAL BARS (reqHistoricalData):
       - Any timeframe from 1 sec to 1 month
       - Includes timestamp
       - Fields: date, open, high, low, close, volume, average, barCount
    """)

    ib.disconnect()
    print("\n[OK] Done")


if __name__ == '__main__':
    main()

"""
Debug market data with error callbacks
"""

from ib_insync import IB, Stock, util
from datetime import datetime, timezone

def onError(reqId, errorCode, errorString, contract):
    print(f"  [ERROR {errorCode}] {errorString}")
    if contract:
        print(f"    Contract: {contract.symbol}")

def main():
    ib = IB()

    # Enable detailed logging
    util.logToConsole()

    utc_now = datetime.now(timezone.utc)
    print("=" * 70)
    print(f"DEBUG MARKET DATA - {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 70)

    ib.connect('127.0.0.1', 4002, clientId=8)
    ib.errorEvent += onError

    print("\n[OK] Connected!")
    print(f"Server version: {ib.client.serverVersion()}")

    # Simple test with SPY
    print("\n" + "-" * 70)
    print("Testing SPY with verbose output...")
    print("-" * 70)

    spy = Stock('SPY', 'SMART', 'USD')
    qualified = ib.qualifyContracts(spy)
    print(f"Qualified: {qualified}")
    print(f"Contract: {spy}")

    # Request market data type 4 (delayed frozen - most lenient)
    print("\nRequesting delayed frozen data (type 4)...")
    ib.reqMarketDataType(4)

    ticker = ib.reqMktData(spy, '', False, False)
    print("Waiting 5 seconds for data...")

    for i in range(5):
        ib.sleep(1)
        print(f"  {i+1}s - Last: {ticker.last}, Bid: {ticker.bid}, Ask: {ticker.ask}, Close: {ticker.close}")

    print(f"\nFinal ticker state:")
    print(f"  {ticker}")

    ib.cancelMktData(spy)
    ib.disconnect()
    print("\n[OK] Done!")

if __name__ == '__main__':
    main()

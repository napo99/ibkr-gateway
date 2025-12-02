#!/usr/bin/env python3
"""Quick connectivity and historical fetch checks for IBKR and Binance."""
import asyncio
from src.data_sources import BinanceClient, IBKRClient


async def main():
    print("=" * 50)
    print("Testing Data Source Connections")
    print("=" * 50)

    # Test IBKR
    print("\n[IBKR] Connecting...")
    ibkr = IBKRClient(symbol='ES')
    connected = ibkr.connect()
    print(f"[IBKR] Connected: {connected}")
    if connected:
        print(f"[IBKR] Contract: {ibkr.contract_symbol}")

        # Fetch some historical data
        print("[IBKR] Fetching 1D of 1-min data...")
        df = ibkr.fetch_historical('1 D', '1 min')
        if df is not None and not df.empty:
            print(f"[IBKR] Got {len(df)} bars")
            print(f"[IBKR] Latest: {df.iloc[-1]['timestamp']} Close: {df.iloc[-1]['close']}")
        else:
            print("[IBKR] No data returned!")

        ibkr.disconnect()

    # Test Binance
    print("\n[Binance] Fetching BTC data...")
    binance = BinanceClient()
    btc_df = await binance.fetch_historical('1m', 100)
    if btc_df is not None and not btc_df.empty:
        print(f"[Binance] Got {len(btc_df)} bars")
        print(f"[Binance] Latest: {btc_df.iloc[-1]['timestamp']} Close: {btc_df.iloc[-1]['close']}")
    else:
        print("[Binance] No data returned!")

    print("\n" + "=" * 50)
    print("Test Complete")


if __name__ == '__main__':
    asyncio.run(main())

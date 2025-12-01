"""Quick Binance test"""
import sys
sys.path.insert(0, 'src')
import asyncio
from data_sources import BinanceClient

async def test():
    client = BinanceClient()
    df = await client.fetch_historical('1h', 24)
    print(f'Fetched {len(df)} BTC hourly bars')
    print(df.tail(3))

asyncio.run(test())

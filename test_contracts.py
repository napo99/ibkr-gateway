"""
Query available ES and NQ futures contracts from IBKR
"""

from ib_insync import IB, Future, ContFuture
import sys

def list_contracts():
    ib = IB()

    print("Connecting to IBKR Gateway (port 4002)...")
    ib.connect('127.0.0.1', 4002, clientId=2)
    print("[OK] Connected!\n")

    # Query ES contracts
    print("=" * 70)
    print("ES (E-mini S&P 500) Futures - CME")
    print("=" * 70)

    es_generic = Future('ES', exchange='CME')
    es_contracts = ib.reqContractDetails(es_generic)

    print(f"Found {len(es_contracts)} ES contracts:\n")
    print(f"{'Symbol':<10} {'Expiry':<12} {'ConID':<12} {'Multiplier':<10} {'Trading Class'}")
    print("-" * 70)

    for cd in sorted(es_contracts, key=lambda x: x.contract.lastTradeDateOrContractMonth)[:8]:
        c = cd.contract
        print(f"{c.localSymbol:<10} {c.lastTradeDateOrContractMonth:<12} {c.conId:<12} {c.multiplier:<10} {c.tradingClass}")

    print(f"\n... and {len(es_contracts) - 8} more contracts")

    # Query NQ contracts
    print("\n" + "=" * 70)
    print("NQ (E-mini NASDAQ 100) Futures - CME")
    print("=" * 70)

    nq_generic = Future('NQ', exchange='CME')
    nq_contracts = ib.reqContractDetails(nq_generic)

    print(f"Found {len(nq_contracts)} NQ contracts:\n")
    print(f"{'Symbol':<10} {'Expiry':<12} {'ConID':<12} {'Multiplier':<10} {'Trading Class'}")
    print("-" * 70)

    for cd in sorted(nq_contracts, key=lambda x: x.contract.lastTradeDateOrContractMonth)[:8]:
        c = cd.contract
        print(f"{c.localSymbol:<10} {c.lastTradeDateOrContractMonth:<12} {c.conId:<12} {c.multiplier:<10} {c.tradingClass}")

    print(f"\n... and {len(nq_contracts) - 8} more contracts")

    # Show front month for both
    print("\n" + "=" * 70)
    print("FRONT MONTH CONTRACTS (Use these for real-time data)")
    print("=" * 70)

    # Get front month ES
    es_front = sorted(es_contracts, key=lambda x: x.contract.lastTradeDateOrContractMonth)[0].contract
    print(f"\nES Front Month: {es_front.localSymbol}")
    print(f"  - Symbol: {es_front.symbol}")
    print(f"  - Expiry: {es_front.lastTradeDateOrContractMonth}")
    print(f"  - Contract ID: {es_front.conId}")
    print(f"  - Multiplier: ${es_front.multiplier}")

    # Get front month NQ
    nq_front = sorted(nq_contracts, key=lambda x: x.contract.lastTradeDateOrContractMonth)[0].contract
    print(f"\nNQ Front Month: {nq_front.localSymbol}")
    print(f"  - Symbol: {nq_front.symbol}")
    print(f"  - Expiry: {nq_front.lastTradeDateOrContractMonth}")
    print(f"  - Contract ID: {nq_front.conId}")
    print(f"  - Multiplier: ${nq_front.multiplier}")

    # Also show continuous futures (for charting)
    print("\n" + "=" * 70)
    print("CONTINUOUS FUTURES (Auto-roll, good for charting)")
    print("=" * 70)
    print("\nNote: Use ContFuture for charts that auto-roll at expiry")
    print("  ES continuous: ContFuture('ES', 'CME')")
    print("  NQ continuous: ContFuture('NQ', 'CME')")

    ib.disconnect()
    print("\n[OK] Done!")

if __name__ == '__main__':
    list_contracts()

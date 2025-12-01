"""
Quick test script to connect to IBKR Paper Trading Account
Requires: IB Gateway or TWS running with API enabled

Paper Trading Ports:
- TWS Paper: 7497
- IB Gateway Paper: 4002

Live Trading Ports (DO NOT USE for testing):
- TWS Live: 7496
- IB Gateway Live: 4001
"""

from ib_insync import IB, util
import sys

# Paper trading ports
TWS_PAPER_PORT = 7497
GATEWAY_PAPER_PORT = 4002

def test_connection(host='127.0.0.1', port=GATEWAY_PAPER_PORT, client_id=1):
    """Test connection to IBKR API"""

    ib = IB()

    print(f"Attempting to connect to IBKR...")
    print(f"  Host: {host}")
    print(f"  Port: {port} ({'Gateway Paper' if port == 4002 else 'TWS Paper' if port == 7497 else 'Unknown'})")
    print(f"  Client ID: {client_id}")
    print("-" * 50)

    try:
        ib.connect(host, port, clientId=client_id)

        print("[OK] CONNECTION SUCCESSFUL!")
        print("-" * 50)

        # Get account info
        print(f"Account(s): {ib.managedAccounts()}")

        # Check if it's a paper account (usually starts with 'D' or 'DU')
        accounts = ib.managedAccounts()
        for acc in accounts:
            if acc.startswith('D'):
                print(f"[OK] Confirmed Paper Trading Account: {acc}")
            else:
                print(f"[WARN] Live Account Detected: {acc} - Be careful!")

        # Get server time
        server_time = ib.reqCurrentTime()
        print(f"Server Time: {server_time}")

        # Try to get ES futures contract info
        print("-" * 50)
        print("Testing ES Futures contract lookup...")

        from ib_insync import Future
        es = Future('ES', exchange='CME')
        ib.qualifyContracts(es)

        if es.conId:
            print(f"[OK] ES Contract found!")
            print(f"  Symbol: {es.symbol}")
            print(f"  Exchange: {es.exchange}")
            print(f"  Contract ID: {es.conId}")
            print(f"  Last Trade Date: {es.lastTradeDateOrContractMonth}")
        else:
            print("[FAIL] Could not qualify ES contract")

        # Disconnect
        ib.disconnect()
        print("-" * 50)
        print("[OK] Test completed successfully!")
        return True

    except ConnectionRefusedError:
        print("[FAIL] CONNECTION REFUSED")
        print("\nPossible issues:")
        print("  1. IB Gateway / TWS is not running")
        print("  2. API is not enabled in Gateway/TWS settings")
        print("  3. Wrong port number")
        print("\nTo fix:")
        print("  - Open IB Gateway or TWS")
        print("  - Go to Configuration > Settings > API > Settings")
        print("  - Check 'Enable ActiveX and Socket Clients'")
        print(f"  - Verify Socket Port is {port}")
        return False

    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        return False

if __name__ == '__main__':
    # Default to Gateway Paper port, can override with command line arg
    port = int(sys.argv[1]) if len(sys.argv) > 1 else GATEWAY_PAPER_PORT

    print("=" * 50)
    print("IBKR Paper Trading Connection Test")
    print("=" * 50)

    success = test_connection(port=port)

    if not success:
        print("\n" + "=" * 50)
        print("Try with TWS port instead?")
        print(f"  py test_ibkr_connection.py {TWS_PAPER_PORT}")
        print("=" * 50)

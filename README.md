# ES/BTC/NQ Correlation Dashboard

Real-time dashboard comparing BTC/USDT with ES futures (and optionally NQ), with correlation, volume context, and live charts.

## Features
- Live WebSocket dashboard (BTC ticks, ES via IBKR)
- Multi-timeframe charts (1m real-time; overlay view)
- Correlation metrics (1m/5m/15m/1h)
- Synchronized crosshairs and TradingView-style measurement
- Dev auto-reload watcher (`dev_watch.py`)

## Requirements
- Python 3.13+
- IBKR Gateway or TWS (running on `127.0.0.1:4002` paper / `4001` live) with CME market data
- Internet connection (Binance WebSocket; no API key needed)

## Installation
```bash
# Install UV if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone <repo-url>
cd ibkr-gateway
uv sync
```

## Usage
```bash
# Run live dashboard
uv run python src/live_server.py
# or with auto-restart + auto-reload
python dev_watch.py
```
Open in the browser:
- Overview (with historical/overlay): `http://127.0.0.1:8765`
- Micro view (real-time focus; hides historical panes): `http://127.0.0.1:8765/micro`

## IBKR Gateway Setup
1. Run IB Gateway/TWS.
2. Configure API: enable socket clients; port `4002` (paper) or `4001` (live); uncheck Read-Only if you need more than data.
3. Ensure CME market data subscription for ES (and NQ if used).

## Project Structure
```
ibkr-gateway/
├─ src/
│  ├─ live_server.py     # WebSocket server + live dashboard
│  ├─ data_sources.py    # IBKR + Binance clients
│  └─ analysis.py        # Correlation calculations
├─ tests/
│  ├─ test_connections.py    # Connectivity/historical fetch check
│  └─ test_sanitization.py   # Sanitization regression tests
├─ dev_watch.py          # Auto-restart server + browser auto-reload
├─ output/               # Generated dashboard HTML (gitignored)
├─ pyproject.toml
├─ uv.lock
└─ README.md
```

## Troubleshooting
- Cannot connect to IBKR: ensure Gateway/TWS is running, correct port, API enabled.
- No ES data: verify CME market data subscription; ES trades Globex Sun 6pm–Fri 5pm ET.
- WebSocket reconnects: brief reconnects are normal; it auto-recovers.

## License
MIT

# BTC vs ES/NQ Correlation Dashboard — Plan (Updated)

Status: V1 running (live dashboard). This doc is simplified to focus on what matters next.

## Phase 1 (done)
- Live BTC/ES charts with correlation overlay.
- Basic measurement, crosshair sync, data streaming.

## Phase 2 (near-term, high-value)

### 1) Volume & VWAP (conviction)
- Enlarge volume panes (20–25% height) for ES/BTC (and NQ if added).
- Rolling 10–20 bar avg on 1m bars; fade sub-avg, brighten >avg; tag spikes >1.5–2x.
- Add VWAP lines; optional small “VWAP↑ 1.6x” tag when crossed with >1.5x vol.
- Header badges: `ES VOL 1.8x | NQ VOL 2.1x` (green >1.5x, yellow 1.0–1.5x, gray <1.0x).

### 2) Volatility strip (context + crypto-specific)
- DVOL (Deribit implied vol for BTC, real-time, free).
- Short-term realized vol: RV15m vs RV60m on 1m bars; show ratio (expanding >1.5, crush <0.5).
- Optional VIX (delayed via ^VIX/yfinance) for context only; live needs CFE subscription.
Display example:
`VOL: RV15 1.2% · RV60 0.7% (1.7x 🔺) · DVOL 52.1 · VIX 14.2 (delayed)`

### 3) Add NQ alongside ES
- NQ price/% in header + its volume badge.
- Optional thin NQ/ES ratio line for tech leadership.

### 4) Divergence awareness (not a trade signal)
- Pill: `DIV: +1.8σ (BTC>ES)` gated by corr>0.4 and RTH hours; else gray.
- Score = (BTC % – ES/NQ %) / recent stddev; only alert on meaningful gaps.

## What to skip (for now)
- CVD/Delta (complex, limited edge).
- VPOC/POC (nice-to-have, not critical).
- Alpha Vantage “free” VIX (limits too tight for real-time).

## Implementation notes (no DB needed)
- Volume averages: rolling 10–20 of 1m bars in memory; session avg from existing backfill if desired.
- DVOL API: `https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC`.
- RV: use last 15 and 60 1m returns; ratio>1.5 = expansion, <0.5 = crush.
- VIX: use delayed ^VIX via yfinance if you want context.

## Fast path to ship
1) Volume panes + VWAP + spike tagging + header volume badges.
2) Volatility strip with DVOL + RV15/60 ratio (optionally delayed VIX).
3) Add NQ feed + header entry; optional NQ/ES ratio line.
- [ ] **5.4**: Data quality validation
  - Compare ES prices with TradingView ES1!
  - Compare BTC prices with CoinMarketCap
  - Check for gaps or anomalies
- [ ] **5.5**: Time synchronization validation
  - Verify timestamps align between sources
  - Check timezone handling (especially DST transitions)
- [ ] **5.6**: Performance testing
  - Measure data fetch times
  - Optimize if > 10 seconds for 7 days of data

**Success Criteria**:
- All test scenarios pass
- Data accuracy validated against reference sources
- Performance acceptable (< 15 seconds total fetch time)

**Deliverable**: Test suite + validation report

---

### Phase 6: Documentation & Deployment ⏳ (Week 4)
**Goal**: Make it easy to use and maintain

#### Documentation:
- [ ] **6.1**: Update README.md
  - Installation instructions (IBKR setup, Python deps)
  - Configuration guide (API keys, ports, etc.)
  - Usage examples
  - Troubleshooting section
- [ ] **6.2**: Code documentation
  - Docstrings for all functions
  - Inline comments for complex logic
  - Type hints for parameters
- [ ] **6.3**: Configuration file
  - Create `config.yaml` or `.env` for settings
  - IBKR host/port
  - Binance API endpoint
  - Data fetch parameters (days, interval, etc.)

#### Deployment:
- [ ] **6.4**: Create `requirements.txt`
- [ ] **6.5**: Optional: Docker container for easy deployment
- [ ] **6.6**: Example Jupyter notebook for interactive use

**Deliverable**: Complete, documented, production-ready system

---

## 🛠️ Technology Stack

### Core Libraries
```python
# Data Fetching
ib_insync==0.9.86          # IBKR API wrapper (or ib_async)
requests==2.31.0           # For Binance REST API
pandas==2.2.0              # Data manipulation

# Visualization (Keep existing)
# TradingView Lightweight Charts (JavaScript, CDN)

# Utilities
python-dotenv==1.0.0       # Environment variables
pyyaml==6.0                # Config files (optional)
```

### Development Tools
```python
# Testing
pytest==7.4.3
pytest-mock==3.12.0

# Code Quality
black==23.12.1             # Code formatting
flake8==7.0.0              # Linting
mypy==1.8.0                # Type checking (optional)
```

---

## 📊 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     User Runs Script                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │   Data Pipeline Orchestrator   │
         └───────────┬───────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌──────────────────┐
│  IBKR Connector │    │ Binance Connector │
│                 │    │                   │
│ - Connect TWS   │    │ - REST API Call   │
│ - Fetch ES data │    │ - Fetch BTC data  │
│ - Contract mgmt │    │ - Rate limiting   │
└────────┬────────┘    └─────────┬─────────┘
         │                       │
         ▼                       ▼
    [ES OHLCV]             [BTC OHLCV]
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Data Synchronization  │
         │                       │
         │ - Timestamp alignment │
         │ - Data validation     │
         │ - Gap detection       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Unified DataFrame    │
         │  [Timestamp, ES, BTC] │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │   Chart Generator     │
         │                       │
         │ - TradingView format  │
         │ - Dual synchronized   │
         │ - HTML output         │
         └───────────┬───────────┘
                     │
                     ▼
            [Interactive HTML Chart]
```

---

## ⚙️ Configuration Design

### `config.yaml` (Proposed)
```yaml
# IBKR Settings
ibkr:
  host: "127.0.0.1"
  port: 7497  # 7497=Paper TWS, 4002=Paper Gateway, 7496=Live TWS
  client_id: 1

  # ES Futures Contract
  futures:
    symbol: "ES"
    exchange: "CME"
    auto_select_front_month: true  # Auto-detect current front month
    # manual_expiry: "20250321"    # Override if needed

# Binance Settings
binance:
  base_url: "https://api.binance.com"  # or api.binance.us
  symbol: "BTCUSDT"  # Most liquid pair
  # Alternative: "BTCUSD" if available

# Data Fetching
data:
  interval: "1m"  # 1m, 5m, 15m, 1h, 1d
  lookback_days: 7
  include_extended_hours: true  # For ES: include after-hours

# Output
output:
  save_to_file: true
  file_format: "html"  # html, csv, json
  output_dir: "./output"

# Error Handling
error_handling:
  max_retries: 3
  retry_delay_seconds: 5
  fallback_to_yfinance: false  # If IBKR fails, use ES=F from yfinance?
```

---

## 🚨 Risk Mitigation & Fallback Strategies

### Potential Issues & Solutions

| Risk | Impact | Mitigation |
|------|--------|------------|
| **IBKR Connection Failure** | No ES data | Retry logic (3x), log errors, optional fallback to yfinance ES=F |
| **Binance Rate Limit** | Delayed BTC data | Exponential backoff, cache data locally |
| **Market Data Subscription Lapse** | No ES data | Alert user, provide setup instructions |
| **ES Contract Rollover** | Wrong contract fetched | Auto-detect front month, handle rollover dates |
| **Time Zone Bugs** | Misaligned data | Force all timestamps to UTC, comprehensive testing |
| **Network Outage** | Script fails | Retry logic, save partial results, resume capability |

---

## ✅ V1 Implementation Completed (2025-12-01)

### What Was Built:
- **Live WebSocket Server** (`src/live_server.py`) - Real-time dashboard served via aiohttp
- **Data Sources** (`src/data_sources.py`) - IBKR + Binance clients with streaming
- **Analysis Module** (`src/analysis.py`) - Correlation calculations, lead/lag analysis
- **Dashboard Generator** (`src/dashboard.py`) - Static HTML generation (superseded by live server)

### Key Changes from Original Plan:
1. **WebSocket-based live updates** instead of static HTML refresh
   - BTC ticks: 20ms throttle (50 updates/sec)
   - ES ticks: 50ms throttle (20 updates/sec)
   - Real-time price sync across all chart timeframes

2. **24-hour backfill** for real-time charts (was originally 30 mins)

3. **Tick-level updates** - Charts update with every tick, not just completed candles

4. **Synchronized crosshairs** between paired charts (ES/BTC real-time, ES/BTC historical)

5. **Measurement tooltip** - Shows price/time/% move when hovering

6. **Visual correlation overlay chart** - Shows both assets on same chart with % change normalization

### Current Limitations Identified:
1. **% Change overlay is misleading** - Shows absolute performance, not actual correlation relationship
2. **Scale mismatch** - ES appears flat because moves are proportionally smaller than BTC
3. **No rolling correlation metric** - Can't see when correlation strengthens/weakens over time
4. **Header vs chart price divergence** - Fixed, but was a UX issue

---

## 📈 V2 Enhancement Ideas (Future Iterations)

### Better Correlation Visualizations

#### 1. Rolling Correlation Line Chart
- Show correlation coefficient over time (e.g., 1-hour rolling window)
- Y-axis: -1 to +1
- Color gradient: Green (+1) → Yellow (0) → Red (-1)
- **Best for**: Seeing when correlation breaks down (trading opportunity)

#### 2. Correlation Heatmap (Time x Timeframe)
- X-axis: Time of day (00:00 to 23:59)
- Y-axis: Different timeframes (1m, 5m, 15m, 1h, 4h)
- Color intensity: Correlation strength
- **Best for**: Finding optimal trading windows

#### 3. Scatter Plot (ES Returns vs BTC Returns)
- X-axis: ES bar-by-bar returns
- Y-axis: BTC bar-by-bar returns
- Tight diagonal line = high correlation
- Scattered points = low correlation
- Add regression line with R² value
- **Best for**: Statistical validation of relationship

#### 4. Spread/Ratio Chart
- Plot ES/BTC ratio (normalized) over time
- Mean-reversion bands (Bollinger-style)
- When spread deviates > 2 std, highlight as divergence signal
- **Best for**: Pairs trading signals

#### 5. TradingView-Style Overlay (Like User's Screenshot)
- BTC candles as primary
- ES as line overlay on secondary axis
- Both Y-axes visible (BTC price right, ES price left)
- Volume histogram at bottom
- **Best for**: Direct visual comparison

#### 6. Lead/Lag Indicator
- Visual indicator showing which asset is leading
- Arrow direction: → ES leads, ← BTC leads
- Lag time in minutes
- Confidence level based on cross-correlation strength

#### 7. Divergence Alert Panel
- Real-time detection when assets decouple
- Severity levels: Minor (yellow), Major (red)
- Duration of divergence
- Historical divergence count

### Technical Improvements

#### Data & Performance
- [ ] Add 3-day, 7-day, 30-day historical data fetch options
- [ ] Database persistence (SQLite or InfluxDB)
- [ ] Data gap detection and alerting
- [ ] Reduce WebSocket message size (binary protocol)

#### UX Improvements
- [ ] Timeframe selector dropdown (1m, 5m, 15m, 1h, 4h, 1D)
- [ ] Dark/Light theme toggle
- [ ] Fullscreen mode for individual charts
- [ ] Export data to CSV
- [ ] Screenshot/share functionality

#### Additional Assets
- [ ] NQ (Nasdaq futures) vs BTC
- [ ] Gold (GC) vs BTC
- [ ] ETH vs ES
- [ ] Multi-asset correlation matrix

#### Alerts & Notifications
- [ ] Browser notifications on divergence
- [ ] Discord/Telegram webhook integration
- [ ] Email alerts for significant correlation changes
- [ ] Sound alerts for divergence events

#### Analytics
- [ ] Correlation breakdown by session (Asia/Europe/US)
- [ ] Volatility-adjusted correlation
- [ ] Granger causality test (who leads statistically?)
- [ ] Correlation regime detection (clustering)

---

## 📊 Correlation Display Comparison

| Visualization | Shows | Best For | Complexity |
|--------------|-------|----------|------------|
| % Change Overlay (current) | Absolute performance | Price comparison | Low |
| Rolling Correlation Line | Correlation over time | Timing trades | Medium |
| Heatmap | Time-of-day patterns | Session analysis | Medium |
| Scatter Plot | Statistical relationship | Validation | Medium |
| Spread Chart | Mean reversion | Pairs trading | Medium |
| TradingView Overlay | Direct price comparison | Visual analysis | Low |

**Recommendation for V2**: Implement Rolling Correlation Line + TradingView-style overlay as priority enhancements.

---

---

## 🎓 Learning Resources

### IBKR API
- [IBKR TWS API Documentation](https://interactivebrokers.github.io/tws-api/)
- [ib_insync Documentation](https://ib-insync.readthedocs.io/)
- [ib_insync GitHub Examples](https://github.com/erdewit/ib_insync/tree/master/notebooks)

### Binance API
- [Binance API Documentation](https://binance-docs.github.io/apidocs/spot/en/)
- [Binance Python Connector](https://github.com/binance/binance-connector-python)

### ES Futures
- [CME E-mini S&P 500 Specs](https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.html)
- [Understanding S&P 500 Futures - Schwab](https://www.schwab.com/learn/story/sp-500-futures-look-basics)

---

## 🤝 Project Team & Roles

- **Developer**: Implementation, testing, deployment
- **Data Validation**: Verify accuracy against reference sources
- **User**: Provide feedback, define requirements

---

## 📅 Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: IBKR Setup | 2-3 days | IBKR account approval |
| Phase 2: Binance API | 1-2 days | None |
| Phase 3: Data Pipeline | 3-4 days | Phase 1 & 2 complete |
| Phase 4: Visualization | 2-3 days | Phase 3 complete |
| Phase 5: Testing | 2-3 days | Phase 4 complete |
| Phase 6: Documentation | 1-2 days | Phase 5 complete |
| **Total** | **2-3 weeks** | - |

*Note: Timeline assumes part-time work (2-3 hours/day)*

---

## ✅ Definition of Done

### MVP Completion Criteria:
1. ✅ Script successfully connects to IBKR paper account
2. ✅ Script successfully fetches BTC data from Binance
3. ✅ Data is synchronized and validated
4. ✅ Interactive HTML chart generated with TradingView quality
5. ✅ ES futures contract auto-detected (front month)
6. ✅ Handles common errors gracefully (connection failures, etc.)
7. ✅ Documentation complete (README, code comments)
8. ✅ Code tested on 3+ different days to verify reliability

---

## 📝 Requirements Confirmed ✅

### **Decisions Made:**

1. **IBKR Account Status** ✅
   - ✅ **Has IBKR account**
   - ✅ **Strategy**: Start with paper trading to test, then subscribe to real-time if signals are good
   - 💡 This allows cost-free testing before committing to subscriptions

2. **Binance Region** ✅
   - ✅ **International** (Binance.com)
   - ✅ **Trading Pair**: BTC/USDT (most liquid, tightest spreads)

3. **Real-time vs Historical** ✅
   - ✅ **PRIORITY**: Real-time streaming data (WebSocket)
   - 💾 **Storage Decision**: Will decide later whether to store 7 or 30 days of historical data
   - 🎯 Focus on live streaming first, historical caching is secondary

4. **Data Storage** ✅
   - ✅ **In-memory only** for now (fresh data on each run)
   - ❌ No CSV/SQLite persistence in MVP
   - 💡 Keeps architecture simple, can add later if needed

5. **Jupyter Integration** ✅
   - ✅ **Jupyter Notebook FIRST** (primary development/testing environment)
   - ✅ If it works well, convert to standalone script later
   - 💡 Interactive development allows faster iteration

6. **Fallback Strategy** ✅
   - ❌ **NO fallback** to yfinance
   - ✅ Error out gracefully with proper logging
   - ✅ Implement robust error messages and log management
   - 💡 Clean failures better than unreliable fallbacks

7. **Correlation Analysis** ✅
   - ✅ **YES** - Include in MVP
   - ✅ Calculate correlation across **multiple timeframes**
   - 🎯 This is a core feature, not an enhancement

8. **Deployment Environment** ✅
   - ✅ **Python script** connecting to IBKR Gateway
   - ✅ Platform-agnostic (Windows/Linux/Mac - Python runs anywhere)
   - ❌ No Docker needed for MVP
   - 💡 Simple Python environment sufficient for testing

---

## 📊 Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Data Approach** | Real-time streaming (NOT historical fetch) | User priority: live correlation analysis |
| **ES Source** | IBKR Paper Account → Real-time if successful | Test with free paper, upgrade if signals good |
| **BTC Source** | Binance.com WebSocket (BTC/USDT) | Largest exchange, free unlimited streaming |
| **Development Env** | Jupyter Notebook first | Interactive testing, faster iteration |
| **Data Storage** | In-memory only (no persistence) | Keep it simple, add later if needed |
| **Fallback Strategy** | NO fallbacks - clean errors + logging | Avoid unreliable data, fail explicitly |
| **Correlation** | Multi-timeframe (1m, 5m, 15m, 1h) | Core feature in MVP, not enhancement |
| **Platform** | Python script (platform-agnostic) | Runs on Windows/Linux/Mac |

---

## 🚀 Next Steps (Immediate Actions)

1. ✅ **Plan finalized** - All questions answered
2. ⏳ **Begin Phase 1** - IBKR Gateway setup + Jupyter notebook
3. ⏳ **Begin Phase 2** - Binance WebSocket + Jupyter notebook (can run in parallel)
4. ⏳ **Phase 3** - Combine both streams
5. ⏳ **Phase 4** - Add live visualization + correlation analysis
6. ⏳ **Test extensively** - Run for multiple hours/days to validate reliability

**Estimated Timeline**: 2-3 weeks (assuming 2-3 hours/day work)

---

**End of Plan Document**

*This is a living document. Update as project progresses.*

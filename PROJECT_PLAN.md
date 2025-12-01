# 📊 BTC vs ES Futures Correlation Analysis - Project Plan

**Status**: 🟡 Planning Phase
**Created**: 2025-12-01
**Last Updated**: 2025-12-01

---

## 🎯 Project Goals

### Primary Objective
Create a professional-grade market correlation tool that compares **Bitcoin (BTC)** price movements against **E-mini S&P 500 Futures (ES)** using institutional-quality data sources.

### Key Success Criteria
1. ✅ Accurate OHLCV data at 1-minute granularity
2. ✅ True 24/7 data coverage for both assets
3. ✅ Professional visualization matching TradingView quality
4. ✅ Reliable data pipeline with error handling
5. ✅ Easy to run and maintain

---

## 🏗️ Architecture Design

### Data Sources Strategy: **Hybrid Streaming Approach (Option 2)**

| Asset | Source | API/Library | Data Type | Cost | Rationale |
|-------|--------|-------------|-----------|------|-----------|
| **ES Futures** | IBKR Paper Account | `ib_insync` / TWS API | **Real-time Stream** | Free (paper) → Paid when moving to live | Institutional-grade futures data, 23.75hr trading |
| **Bitcoin** | Binance.com | Binance WebSocket API | **Real-time Stream** | Free (unlimited) | Largest crypto exchange, most accurate price discovery |

### Why Hybrid?
- ✅ **Best of both worlds**: Professional ES data + Free accurate BTC data
- ✅ **Cost-effective**: Only need IBKR subscription for ES (BTC is free from Binance)
- ✅ **Reliability**: Two independent data sources
- ✅ **Simplicity**: Binance API easier than IBKR crypto (no Paxos permissions)
- ✅ **Accuracy**: Using primary price discovery venues for each asset

---

## 📐 Technical Specifications

### Data Requirements

#### Timeframes Supported
- **Primary**: 1-minute bars (OHLCV) via real-time streaming
- **Correlation Analysis**: Multiple timeframes (1m, 5m, 15m, 1h)
- **Future**: Daily (1d) for longer-term analysis

#### Data Storage Strategy
- **MVP**: In-memory only (no persistence)
- **Future Decision**: Optionally store 7-30 days of historical data
- **Streaming Priority**: Focus on live data first, caching is secondary

#### Data Fields
```python
{
    'timestamp': datetime,  # UTC, aligned to minute boundaries
    'open': float,
    'high': float,
    'low': float,
    'close': float,
    'volume': float
}
```

---

## 🔧 Implementation Phases

### Phase 1: IBKR Streaming Setup ⏳ (Week 1)
**Goal**: Establish real-time ES futures data stream from IBKR paper account

#### Tasks:
- [ ] **1.1**: Configure IBKR paper trading account credentials
- [ ] **1.2**: Install IB Gateway (preferred for headless operation)
- [ ] **1.3**: Configure API settings (port 4002 for paper Gateway)
- [ ] **1.4**: Install `ib_insync` library
- [ ] **1.5**: Write connection test script for Jupyter
- [ ] **1.6**: Implement ES futures contract auto-detection (front month)
- [ ] **1.7**: Set up real-time bar streaming (reqRealTimeBars or reqMktData)
- [ ] **1.8**: Test receiving live 5-second ES data updates
- [ ] **1.9**: Aggregate 5-second bars into 1-minute OHLCV candles
- [ ] **1.10**: Implement proper logging for connection events

**Success Criteria**:
- Can connect to IBKR API from Jupyter notebook
- Real-time ES data streaming successfully (5-sec or 1-min bars)
- Data aggregates correctly into 1-minute OHLCV candles
- Handles reconnection if stream disconnects
- Clean error messages logged

**Deliverable**: Jupyter notebook `01_ibkr_streaming.ipynb`

---

### Phase 2: Binance WebSocket Streaming ⏳ (Week 1)
**Goal**: Real-time Bitcoin streaming from Binance.com

#### Tasks:
- [ ] **2.1**: Research Binance WebSocket API (Kline/Candlestick streams)
- [ ] **2.2**: Confirm: Binance.com (international) ✅
- [ ] **2.3**: Confirm: BTC/USDT trading pair ✅
- [ ] **2.4**: Install `websocket-client` or `python-binance` library
- [ ] **2.5**: Set up WebSocket connection to btcusdt@kline_1m stream
- [ ] **2.6**: Parse incoming 1-minute candlestick data
- [ ] **2.7**: Implement reconnection logic for dropped connections
- [ ] **2.8**: Test WebSocket stability (run for 1+ hour)
- [ ] **2.9**: Implement timestamp synchronization with IBKR data (UTC alignment)
- [ ] **2.10**: Add proper logging for WebSocket events

**Success Criteria**:
- WebSocket connects and receives real-time BTC/USDT 1m candles
- Timestamps align with IBKR data (same UTC minute boundaries)
- Auto-reconnects on connection loss
- Data validated against Binance web UI / TradingView
- Clean error logging

**Deliverable**: Jupyter notebook `02_binance_streaming.ipynb`

---

### Phase 3: Unified Streaming Pipeline ⏳ (Week 2)
**Goal**: Combine both real-time streams into synchronized data structure

#### Tasks:
- [ ] **3.1**: Design in-memory data structure (dual pandas DataFrames)
  - ES DataFrame: timestamp, O, H, L, C, V
  - BTC DataFrame: timestamp, O, H, L, C, V
- [ ] **3.2**: Implement dual-stream manager class
  - Manages both IBKR and Binance connections
  - Aggregates incoming ticks into 1-minute candles
- [ ] **3.3**: Timestamp synchronization
  - Align both streams to same UTC minute boundaries
  - Handle clock drift between sources
- [ ] **3.4**: Data validation in real-time
  - Flag gaps in data stream
  - Detect anomalies (flat candles, extreme price moves)
  - Volume sanity checks
- [ ] **3.5**: Error handling (NO fallbacks, clean failures)
  - IBKR disconnect → log error, attempt reconnect
  - Binance disconnect → log error, attempt reconnect
  - Both down → stop and alert user
  - Implement circuit breaker pattern
- [ ] **3.6**: Logging infrastructure
  - Structured logging (timestamp, level, source, message)
  - Separate log files for ES and BTC streams
  - Summary statistics logged every 5 minutes

**Success Criteria**:
- Both streams running simultaneously in Jupyter
- Data synchronized to same minute boundaries
- Handles disconnections gracefully (auto-reconnect)
- Comprehensive logging visible in notebook
- No fallback to unreliable sources

**Deliverable**: Jupyter notebook `03_unified_streaming.ipynb`

---

### Phase 4: Live Visualization + Correlation ⏳ (Week 2-3)
**Goal**: Real-time charts with correlation analysis across multiple timeframes

#### Current Design to Keep (from Gemini):
- ✅ TradingView Lightweight Charts library
- ✅ Synchronized dual-chart layout (BTC top, ES bottom)
- ✅ Dark theme (#131722 background)
- ✅ Zoom/pan synchronization
- ✅ Crosshair synchronization

#### New Features to Add:
- [ ] **4.1**: Update to streaming data instead of static HTML
  - Chart updates in real-time as new 1m candles arrive
  - Auto-scroll to keep latest data visible
- [ ] **4.2**: Update chart labels
  - "ES Futures (CME via IBKR Paper)"
  - "BTC/USDT (Binance.com)"
- [ ] **4.3**: **Multi-timeframe correlation analysis** (CORE FEATURE)
  - Calculate rolling correlation for 1m, 5m, 15m, 1h windows
  - Display correlation coefficient panel below charts
  - Color-coded: Green (>0.5), Yellow (0-0.5), Red (<0)
  - Update correlation in real-time
- [ ] **4.4**: Add volume bars below each price chart
- [ ] **4.5**: Correlation divergence alerts
  - Detect when correlation breaks down significantly
  - Visual indicator when correlation < 0.2 (unusual)
- [ ] **4.6**: Timestamp display
  - Show UTC time
  - Format: "2025-12-01 14:35:00 UTC"
  - Display last update time

#### Live Chart Implementation:
- [ ] **4.7**: Implement auto-refresh mechanism
  - Update chart every 60 seconds (new 1m candle)
  - Use IPython display for Jupyter updates
- [ ] **4.8**: Chart performance optimization
  - Limit visible data to last 500 candles
  - Keep full dataset in memory for correlation calc

**Success Criteria**:
- Charts update automatically with live data
- Correlation calculated across 4 timeframes (1m, 5m, 15m, 1h)
- Visual quality matches Gemini's design
- All interactive features work (zoom, pan, crosshair)
- Correlation panel updates every minute

**Deliverable**: Jupyter notebook `04_live_visualization.ipynb`

---

### Phase 5: Testing & Validation ⏳ (Week 3)
**Goal**: Ensure reliability and accuracy

#### Test Scenarios:
- [ ] **5.1**: Normal operation (both APIs working)
- [ ] **5.2**: IBKR connection failure
  - Test fallback behavior (error message or retry)
- [ ] **5.3**: Binance API failure
  - Test fallback (try backup exchange?)
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

## 📈 Future Enhancements (Post-MVP)

### Phase 7+: Advanced Features
- [ ] Real-time streaming (WebSocket for both sources)
- [ ] Statistical correlation analysis
  - Rolling correlation coefficient
  - Lead/lag analysis (does ES lead BTC or vice versa?)
  - Correlation breakdown by time of day
- [ ] Alert system
  - Notify when correlation breaks down
  - Divergence detection
- [ ] Multiple timeframe analysis (1m, 5m, 1h simultaneously)
- [ ] Additional assets (ETH, NQ futures, Gold futures)
- [ ] Backtesting framework
- [ ] Live dashboard (auto-refresh every minute)
- [ ] Database storage (PostgreSQL/InfluxDB for timeseries)
- [ ] Cloud deployment (AWS/GCP)

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

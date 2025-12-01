import yfinance as yf
import pandas as pd
import json
from datetime import datetime

def fetch_data(ticker, period, interval):
    """
    Fetches historical data for a given ticker.
    """
    print(f"Fetching {ticker} data (Period: {period}, Interval: {interval})...")
    try:
        # explicit auto_adjust=False to try and preserve OHLC
        data = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
        
        # Handle MultiIndex columns (yfinance > 0.2.x)
        if isinstance(data.columns, pd.MultiIndex):
            try:
                if 'Ticker' in data.columns.names:
                    data.columns = data.columns.droplevel('Ticker')
                elif len(data.columns.levels) == 2:
                     data.columns = data.columns.droplevel(1)
            except Exception as e:
                print(f"Error flattening columns: {e}")

        if data.empty:
            print(f"Warning: No data found for {ticker}")
            return None
        
        # Reset index to make Date/Datetime a column
        data = data.reset_index()
        return data
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def format_data_for_tv(data, is_daily=False):
    """
    Formats DataFrame to TradingView JSON format.
    """
    # Ensure data is sorted and unique
    date_col = 'Date' if 'Date' in data.columns else 'Datetime'
    data = data.sort_values(by=date_col).drop_duplicates(subset=[date_col])
    
    # Drop NaNs
    data = data.dropna(subset=['Open', 'High', 'Low', 'Close'])

    tv_data = []
    for index, row in data.iterrows():
        time_val = row[date_col]
        
        if is_daily:
            # Use YYYY-MM-DD string for daily charts
            if isinstance(time_val, pd.Timestamp):
                time_val = time_val.strftime('%Y-%m-%d')
            else:
                # Fallback if it's already a string or something else
                time_val = str(time_val).split(' ')[0]
        else:
            # Use unix timestamp for intraday
            if isinstance(time_val, pd.Timestamp):
                time_val = int(time_val.timestamp())
        
        # For Area/Line charts, we just need time and value (close)
        # But we keep full structure for flexibility
        tv_data.append({
            'time': time_val,
            'open': row['Open'],
            'high': row['High'],
            'low': row['Low'],
            'close': row['Close'],
            'value': row['Close'] # For Area/Line series
        })
    return tv_data

def is_data_flat(data):
    """Checks if Open is essentially equal to Close for most points."""
    if data is None or data.empty:
        return False
    # Check first 100 points or all
    subset = data.head(100)
    matches = (subset['Open'] == subset['Close']).sum()
    return matches > (len(subset) * 0.9)

def generate_chart_html(btc_data, spx_data, title, is_daily=False, force_chart_type=None):
    """
    Generates the HTML string for the TradingView chart.
    Returns the HTML string.
    """
    btc_formatted = format_data_for_tv(btc_data, is_daily)
    spx_formatted = format_data_for_tv(spx_data, is_daily)
    
    btc_json = json.dumps(btc_formatted)
    spx_json = json.dumps(spx_formatted)

    # Determine chart type based on data flatness
    btc_flat = is_data_flat(btc_data)
    
    if force_chart_type:
        chart_type = force_chart_type
    else:
        # Auto-detect: if flat, use Area. Else Candlestick.
        chart_type = 'Area' if btc_flat else 'Candlestick'
    
    print(f"Chart Type: {chart_type} (BTC Flat: {btc_flat})")

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <script src="lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ background-color: #131722; color: #d1d4dc; font-family: sans-serif; margin: 0; padding: 20px; }}
        .chart-container {{ width: 100%; height: 400px; margin-bottom: 20px; }}
        h2 {{ margin: 0 0 10px 0; font-size: 16px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    
    <h2>Bitcoin (BTC-USD)</h2>
    <div id="chart_btc" class="chart-container"></div>
    
    <h2>S&P 500 (^GSPC)</h2>
    <div id="chart_spx" class="chart-container"></div>

    <script>
        const btcData = {btc_json};
        const spxData = {spx_json};
        const chartType = '{chart_type}';

        function createChart(containerId, data, colorUp, colorDown) {{
            const chart = LightweightCharts.createChart(document.getElementById(containerId), {{
                layout: {{
                    background: {{ type: 'solid', color: '#131722' }},
                    textColor: '#d1d4dc',
                }},
                grid: {{
                    vertLines: {{ color: '#363c4e' }},
                    horzLines: {{ color: '#363c4e' }},
                }},
                timeScale: {{
                    timeVisible: true,
                    secondsVisible: false,
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                }},
            }});

            let series;
            if (chartType === 'Area') {{
                series = chart.addAreaSeries({{
                    topColor: 'rgba(38, 166, 154, 0.56)',
                    bottomColor: 'rgba(38, 166, 154, 0.04)',
                    lineColor: 'rgba(38, 166, 154, 1)',
                    lineWidth: 2,
                }});
            }} else {{
                series = chart.addCandlestickSeries({{
                    upColor: colorUp,
                    downColor: colorDown,
                    borderVisible: false,
                    wickUpColor: colorUp,
                    wickDownColor: colorDown,
                }});
            }}

            series.setData(data);
            
            return {{ chart, series }};
        }}

        // Create Charts
        const btc = createChart('chart_btc', btcData, '#26a69a', '#ef5350');
        const spx = createChart('chart_spx', spxData, '#26a69a', '#ef5350');

        // --- Synchronization Logic ---

        // 1. Sync Visible Range (Zoom/Pan)
        function syncVisibleRange(sourceChart, targetChart) {{
            sourceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
                if (range) {{
                    targetChart.timeScale().setVisibleLogicalRange(range);
                }}
            }});
        }}

        syncVisibleRange(btc.chart, spx.chart);
        syncVisibleRange(spx.chart, btc.chart);

        // 2. Sync Crosshair (Cursor)
        function syncCrosshair(sourceChart, sourceSeries, sourceData, targetChart, targetSeries, targetData) {{
            sourceChart.subscribeCrosshairMove(param => {{
                if (!param.time || param.point.x < 0 || param.point.x > sourceChart.timeScale().width() || param.point.y < 0 || param.point.y > sourceChart.timeScale().height()) {{
                    targetChart.clearCrosshairPosition();
                    return;
                }}

                let timeToSearch = param.time;
                // Handle Business Day Object (Daily Charts)
                if (typeof param.time === 'object' && param.time.year) {{
                    timeToSearch = param.time.year + '-' + 
                                   String(param.time.month).padStart(2, '0') + '-' + 
                                   String(param.time.day).padStart(2, '0');
                }}

                const dataPoint = targetData.find(d => d.time === timeToSearch);

                if (dataPoint) {{
                    targetChart.setCrosshairPosition(dataPoint.close, timeToSearch, targetSeries);
                }} else {{
                    targetChart.clearCrosshairPosition();
                }}
            }});
        }}

        syncCrosshair(btc.chart, btc.series, btcData, spx.chart, spx.series, spxData);
        syncCrosshair(spx.chart, spx.series, spxData, btc.chart, btc.series, btcData);

        // Fit Content
        btc.chart.timeScale().fitContent();
        spx.chart.timeScale().fitContent();
        
        // Resize handling
        window.addEventListener('resize', () => {{
            btc.chart.resize(document.body.clientWidth - 40, 400);
            spx.chart.resize(document.body.clientWidth - 40, 400);
        }});
    </script>
</body>
</html>
    """
    return html_content

def save_html_file(html_content, filename):
    with open(f"{filename}.html", "w") as f:
        f.write(html_content)
    print(f"Saved {filename}.html")

def get_notebook_chart(period="7d", interval="1m", is_daily=False):
    """
    Helper function to be used in a Jupyter Notebook.
    Fetches data and returns the HTML object for display.
    
    Usage in Notebook:
        from market_chart_tv import get_notebook_chart
        from IPython.display import HTML
        
        html_str = get_notebook_chart(period="7d", interval="1m")
        HTML(html_str)
    """
    print(f"Fetching data for Notebook (Period: {period}, Interval: {interval})...")
    btc_data = fetch_data("BTC-USD", period=period, interval=interval)
    spx_data = fetch_data("^GSPC", period=period, interval=interval)
    
    if btc_data is None or spx_data is None:
        return "<h3>Error fetching data</h3>"
        
    title = f"BTC vs S&P 500 - {period} ({interval})"
    html_content = generate_chart_html(btc_data, spx_data, title, is_daily=is_daily)
    return html_content

def main():
    # 1. Short-term: 1m data for last 7 days
    print("--- Generating Short-Term TradingView Chart (1m, 7d) ---")
    btc_1m = fetch_data("BTC-USD", period="7d", interval="1m")
    spx_1m = fetch_data("^GSPC", period="7d", interval="1m")
    
    if btc_1m is not None and spx_1m is not None:
        html_1m = generate_chart_html(btc_1m, spx_1m, "BTC vs S&P 500 - Last 7 Days (1m)", is_daily=False)
        save_html_file(html_1m, "tv_chart_7d_1m")

    # 2. Long-term: 1d data for last 2 years
    print("\n--- Generating Long-Term TradingView Chart (1d, 2y) ---")
    btc_1d = fetch_data("BTC-USD", period="2y", interval="1d")
    spx_1d = fetch_data("^GSPC", period="2y", interval="1d")

    if btc_1d is not None and spx_1d is not None:
        html_1d = generate_chart_html(btc_1d, spx_1d, "BTC vs S&P 500 - Last 2 Years (Daily)", is_daily=True, force_chart_type='Candlestick')
        save_html_file(html_1d, "tv_chart_2y_1d")

if __name__ == "__main__":
    main()

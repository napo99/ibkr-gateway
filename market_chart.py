import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, timedelta

def fetch_data(ticker, period, interval):
    """
    Fetches historical data for a given ticker.
    """
    print(f"Fetching {ticker} data (Period: {period}, Interval: {interval})...")
    try:
        data = yf.download(ticker, period=period, interval=interval, progress=False)
        # Handle MultiIndex columns (yfinance > 0.2.x)
        if isinstance(data.columns, pd.MultiIndex):
            try:
                # Drop the 'Ticker' level if it exists
                if 'Ticker' in data.columns.names:
                    data.columns = data.columns.droplevel('Ticker')
                # Fallback: if just 2 levels and 2nd is ticker symbol
                elif len(data.columns.levels) == 2:
                     data.columns = data.columns.droplevel(1)
            except Exception as e:
                print(f"Error flattening columns: {e}")

        if data.empty:
            print(f"Warning: No data found for {ticker}")
            return None
            
        print(f"--- Debug {ticker} ---")
        print(data.head(2))
        print(data.columns)
        print("---------------------")
        return data
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def create_chart(btc_data, spx_data, title, filename):
    """
    Creates a 2-pane OHLC chart using Plotly.
    """
    if btc_data is None or spx_data is None:
        print(f"Skipping chart {title} due to missing data.")
        return

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=("Bitcoin (BTC-USD)", "S&P 500 (^GSPC)"),
        row_heights=[0.5, 0.5]
    )

    # BTC OHLC
    fig.add_trace(go.Candlestick(
        x=btc_data.index,
        open=btc_data['Open'],
        high=btc_data['High'],
        low=btc_data['Low'],
        close=btc_data['Close'],
        name='BTC-USD',
        increasing_line_color='#26A69A',  # TradingView Green
        decreasing_line_color='#EF5350'   # TradingView Red
    ), row=1, col=1)

    # SPX OHLC
    fig.add_trace(go.Candlestick(
        x=spx_data.index,
        open=spx_data['Open'],
        high=spx_data['High'],
        low=spx_data['Low'],
        close=spx_data['Close'],
        name='S&P 500',
        increasing_line_color='#26A69A',
        decreasing_line_color='#EF5350'
    ), row=2, col=1)

    # Calculate default zoom range (last 6 hours)
    last_date = btc_data.index[-1]
    start_zoom = last_date - timedelta(hours=6)

    fig.update_layout(
        title=title,
        yaxis_title='BTC Price (USD)',
        yaxis2_title='S&P 500 Points',
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        height=900,
        template="plotly_dark",
        showlegend=False,
        plot_bgcolor='#131722',
        paper_bgcolor='#131722',
        font=dict(color='#d1d4dc'),
        xaxis=dict(range=[start_zoom, last_date]), # Set default zoom
        xaxis2=dict(matches='x') # Ensure both axes zoom together
    )
    
    fig.update_xaxes(showgrid=True, gridcolor='#363c4e')
    fig.update_yaxes(showgrid=True, gridcolor='#363c4e')

    output_path = f"{filename}.html"
    fig.write_html(output_path)
    print(f"Chart saved to {output_path}")

def main():
    # 1. Short-term: 1m data for last 7 days
    # Note: yfinance 1m data is limited to 7 days.
    print("--- Generating Short-Term Chart (1m, 7d) ---")
    btc_1m = fetch_data("BTC-USD", period="7d", interval="1m")
    
    # S&P 500 index (^GSPC) often doesn't have 1m data available via free yfinance API.
    # We will try ^GSPC first, if empty/fail, we might try SPY as proxy, but let's stick to user request first.
    spx_1m = fetch_data("^GSPC", period="7d", interval="1m")
    
    if spx_1m is None or spx_1m.empty:
        print("Retrying S&P 500 with SPY (ETF) as proxy for 1m data...")
        spx_1m = fetch_data("SPY", period="7d", interval="1m")

    create_chart(btc_1m, spx_1m, "BTC vs S&P 500 - Last 7 Days (1 Minute Interval)", "chart_7d_1m")

    # 2. Long-term: 1d data for last 2 years
    print("\n--- Generating Long-Term Chart (1d, 2y) ---")
    btc_1d = fetch_data("BTC-USD", period="2y", interval="1d")
    spx_1d = fetch_data("^GSPC", period="2y", interval="1d")

    create_chart(btc_1d, spx_1d, "BTC vs S&P 500 - Last 2 Years (Daily Interval)", "chart_2y_1d")

if __name__ == "__main__":
    main()

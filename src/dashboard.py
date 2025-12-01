"""
TradingView Lightweight Charts Dashboard Generator
Auto-refreshing HTML with correlation visualization
"""

import json
from datetime import datetime, timezone
from typing import Optional


class DashboardGenerator:
    """Generate HTML dashboard with TradingView charts"""

    TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="{refresh_interval}">
    <title>ES/BTC Correlation Dashboard</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #0a0a0f;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow-x: hidden;
        }}
        .header {{
            background: linear-gradient(180deg, #1a1a2e 0%, #0a0a0f 100%);
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #2a2a3e;
        }}
        .header h1 {{
            font-size: 18px;
            font-weight: 500;
            color: #fff;
        }}
        .header .time {{
            font-size: 13px;
            color: #787b86;
        }}
        .correlation-bar {{
            display: flex;
            justify-content: center;
            gap: 30px;
            padding: 10px 20px;
            background: #12121a;
            border-bottom: 1px solid #2a2a3e;
        }}
        .corr-item {{
            text-align: center;
        }}
        .corr-label {{
            font-size: 11px;
            color: #787b86;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .corr-value {{
            font-size: 24px;
            font-weight: 600;
            margin-top: 4px;
        }}
        .corr-detail {{
            font-size: 11px;
            color: #787b86;
            margin-top: 2px;
        }}
        .lead-lag {{
            padding: 8px 16px;
            background: #1a1a2e;
            text-align: center;
            font-size: 13px;
        }}
        .lead-lag .leader {{
            color: #00C853;
            font-weight: 600;
        }}
        .charts-container {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1px;
            background: #2a2a3e;
        }}
        .chart-wrapper {{
            background: #0a0a0f;
            position: relative;
            min-height: 250px;
        }}
        #es-realtime, #btc-realtime {{
            height: 250px;
        }}
        #es-historical, #btc-historical {{
            height: 220px;
        }}
        .chart-label {{
            position: absolute;
            top: 10px;
            left: 15px;
            z-index: 10;
            font-size: 12px;
            color: #787b86;
            background: rgba(10, 10, 15, 0.8);
            padding: 4px 8px;
            border-radius: 4px;
        }}
        .chart-label .symbol {{
            color: #fff;
            font-weight: 600;
            font-size: 14px;
        }}
        .chart-label .price {{
            color: {es_color};
            font-size: 18px;
            font-weight: 600;
        }}
        .section-title {{
            padding: 15px 20px 10px;
            font-size: 14px;
            color: #787b86;
            text-transform: uppercase;
            letter-spacing: 1px;
            border-top: 1px solid #2a2a3e;
        }}
        .divergence-bar {{
            height: 4px;
            background: linear-gradient(90deg, {divergence_gradient});
            margin: 0 20px 10px;
            border-radius: 2px;
        }}
        .legend {{
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 10px;
            font-size: 11px;
            color: #787b86;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .legend-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>ES / BTC Correlation Dashboard</h1>
        <div class="time">Updated: {last_update} UTC | Auto-refresh: {refresh_interval}s</div>
    </div>

    <div class="correlation-bar">
        <div class="corr-item">
            <div class="corr-label">1 Min</div>
            <div class="corr-value" style="color: {corr_1m_color}">{corr_1m}</div>
            <div class="corr-detail">{corr_1m_strength}</div>
        </div>
        <div class="corr-item">
            <div class="corr-label">5 Min</div>
            <div class="corr-value" style="color: {corr_5m_color}">{corr_5m}</div>
            <div class="corr-detail">{corr_5m_strength}</div>
        </div>
        <div class="corr-item">
            <div class="corr-label">15 Min</div>
            <div class="corr-value" style="color: {corr_15m_color}">{corr_15m}</div>
            <div class="corr-detail">{corr_15m_strength}</div>
        </div>
        <div class="corr-item">
            <div class="corr-label">1 Hour</div>
            <div class="corr-value" style="color: {corr_1h_color}">{corr_1h}</div>
            <div class="corr-detail">{corr_1h_strength}</div>
        </div>
    </div>

    <div class="lead-lag">
        Lead/Lag Analysis: <span class="leader">{lead_lag_text}</span>
    </div>

    <div class="section-title">Real-Time (Last 30 min) - 1 Min Candles</div>
    <div class="charts-container">
        <div class="chart-wrapper">
            <div class="chart-label">
                <span class="symbol">ES {es_contract}</span><br>
                <span class="price" style="color: #2962FF">{es_price}</span>
            </div>
            <div id="es-realtime"></div>
        </div>
        <div class="chart-wrapper">
            <div class="chart-label">
                <span class="symbol">BTC/USDT</span><br>
                <span class="price" style="color: #FF9800">{btc_price}</span>
            </div>
            <div id="btc-realtime"></div>
        </div>
    </div>

    <div class="section-title">Historical (Last 7 Days) - 1 Hour Candles</div>
    <div class="divergence-bar"></div>
    <div class="charts-container">
        <div class="chart-wrapper">
            <div id="es-historical"></div>
        </div>
        <div class="chart-wrapper">
            <div id="btc-historical"></div>
        </div>
    </div>

    <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background: #00C853"></div> Strong Correlation (&gt;0.7)</div>
        <div class="legend-item"><div class="legend-dot" style="background: #FFD600"></div> Moderate (0.4-0.7)</div>
        <div class="legend-item"><div class="legend-dot" style="background: #FF9100"></div> Weak (0.2-0.4)</div>
        <div class="legend-item"><div class="legend-dot" style="background: #FF1744"></div> Divergence (&lt;0.2)</div>
    </div>

    <script>
        const chartOptions = {{
            layout: {{
                background: {{ type: 'solid', color: '#0a0a0f' }},
                textColor: '#787b86',
            }},
            grid: {{
                vertLines: {{ color: '#1a1a2e' }},
                horzLines: {{ color: '#1a1a2e' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
            }},
            rightPriceScale: {{
                borderColor: '#2a2a3e',
            }},
            timeScale: {{
                borderColor: '#2a2a3e',
                timeVisible: true,
                secondsVisible: false,
            }},
        }};

        // ES Real-time
        const esRtChart = LightweightCharts.createChart(document.getElementById('es-realtime'), {{
            ...chartOptions, width: document.getElementById('es-realtime').offsetWidth, height: 250
        }});
        const esRtCandles = esRtChart.addCandlestickSeries({{
            upColor: '#26a69a', downColor: '#ef5350',
            borderUpColor: '#26a69a', borderDownColor: '#ef5350',
            wickUpColor: '#26a69a', wickDownColor: '#ef5350',
        }});
        esRtCandles.setData({es_realtime_data});
        const esRtVolume = esRtChart.addHistogramSeries({{
            color: '#26a69a', priceFormat: {{ type: 'volume' }}, priceScaleId: '',
        }});
        esRtVolume.priceScale().applyOptions({{ scaleMargins: {{ top: 0.85, bottom: 0 }} }});
        esRtVolume.setData({es_realtime_volume});

        // BTC Real-time
        const btcRtChart = LightweightCharts.createChart(document.getElementById('btc-realtime'), {{
            ...chartOptions, width: document.getElementById('btc-realtime').offsetWidth, height: 250
        }});
        const btcRtCandles = btcRtChart.addCandlestickSeries({{
            upColor: '#FF9800', downColor: '#F44336',
            borderUpColor: '#FF9800', borderDownColor: '#F44336',
            wickUpColor: '#FF9800', wickDownColor: '#F44336',
        }});
        btcRtCandles.setData({btc_realtime_data});
        const btcRtVolume = btcRtChart.addHistogramSeries({{
            color: '#FF9800', priceFormat: {{ type: 'volume' }}, priceScaleId: '',
        }});
        btcRtVolume.priceScale().applyOptions({{ scaleMargins: {{ top: 0.85, bottom: 0 }} }});
        btcRtVolume.setData({btc_realtime_volume});

        // ES Historical
        const esHistChart = LightweightCharts.createChart(document.getElementById('es-historical'), {{
            ...chartOptions, width: document.getElementById('es-historical').offsetWidth, height: 220
        }});
        const esHistCandles = esHistChart.addCandlestickSeries({{
            upColor: '#26a69a', downColor: '#ef5350',
            borderUpColor: '#26a69a', borderDownColor: '#ef5350',
            wickUpColor: '#26a69a', wickDownColor: '#ef5350',
        }});
        esHistCandles.setData({es_historical_data});

        // BTC Historical
        const btcHistChart = LightweightCharts.createChart(document.getElementById('btc-historical'), {{
            ...chartOptions, width: document.getElementById('btc-historical').offsetWidth, height: 220
        }});
        const btcHistCandles = btcHistChart.addCandlestickSeries({{
            upColor: '#FF9800', downColor: '#F44336',
            borderUpColor: '#FF9800', borderDownColor: '#F44336',
            wickUpColor: '#FF9800', wickDownColor: '#F44336',
        }});
        btcHistCandles.setData({btc_historical_data});

        // Sync crosshairs
        function syncCrosshair(chart, point) {{
            if (point) {{
                chart.setCrosshairPosition(point.seriesData.get(chart.getSeries()[0]) || point.seriesData.values().next().value, point.time, chart.getSeries()[0]);
            }} else {{
                chart.clearCrosshairPosition();
            }}
        }}

        esRtChart.subscribeCrosshairMove(param => syncCrosshair(btcRtChart, param));
        btcRtChart.subscribeCrosshairMove(param => syncCrosshair(esRtChart, param));
        esHistChart.subscribeCrosshairMove(param => syncCrosshair(btcHistChart, param));
        btcHistChart.subscribeCrosshairMove(param => syncCrosshair(esHistChart, param));

        // Responsive resize
        window.addEventListener('resize', () => {{
            esRtChart.applyOptions({{ width: document.getElementById('es-realtime').offsetWidth }});
            btcRtChart.applyOptions({{ width: document.getElementById('btc-realtime').offsetWidth }});
            esHistChart.applyOptions({{ width: document.getElementById('es-historical').offsetWidth }});
            btcHistChart.applyOptions({{ width: document.getElementById('btc-historical').offsetWidth }});
        }});
    </script>
</body>
</html>'''

    def __init__(self, output_path: str = 'output/dashboard.html', refresh_interval: int = 60):
        self.output_path = output_path
        self.refresh_interval = refresh_interval

    def _format_ohlcv(self, data: list) -> str:
        """Format OHLCV data for TradingView"""
        return json.dumps([{
            'time': d['time'],
            'open': d['open'],
            'high': d['high'],
            'low': d['low'],
            'close': d['close']
        } for d in data])

    def _format_volume(self, data: list) -> str:
        """Format volume data for TradingView"""
        return json.dumps([{
            'time': d['time'],
            'value': d['volume'],
            'color': '#26a69a80' if d['close'] >= d['open'] else '#ef535080'
        } for d in data])

    def generate(self,
                 es_realtime: list,
                 btc_realtime: list,
                 es_historical: list,
                 btc_historical: list,
                 correlation_results: dict,
                 es_contract: str = 'ESZ5',
                 lead_lag_text: str = 'Analyzing...') -> str:
        """Generate dashboard HTML"""

        # Get latest prices
        es_price = f"{es_realtime[-1]['close']:.2f}" if es_realtime else "N/A"
        btc_price = f"{btc_realtime[-1]['close']:.2f}" if btc_realtime else "N/A"

        # Determine ES price color
        if es_realtime and len(es_realtime) > 1:
            es_color = "#26a69a" if es_realtime[-1]['close'] >= es_realtime[-2]['close'] else "#ef5350"
        else:
            es_color = "#787b86"

        # Correlation values
        corr_1m = correlation_results.get('1m', {})
        corr_5m = correlation_results.get('5m', {})
        corr_15m = correlation_results.get('15m', {})
        corr_1h = correlation_results.get('1h', {})

        html = self.TEMPLATE.format(
            refresh_interval=self.refresh_interval,
            last_update=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            es_contract=es_contract,
            es_price=es_price,
            btc_price=btc_price,
            es_color=es_color,

            # Correlation values
            corr_1m=f"{corr_1m.get('correlation', 0):.2f}",
            corr_1m_color=corr_1m.get('color', '#787b86'),
            corr_1m_strength=corr_1m.get('strength', 'N/A'),
            corr_5m=f"{corr_5m.get('correlation', 0):.2f}",
            corr_5m_color=corr_5m.get('color', '#787b86'),
            corr_5m_strength=corr_5m.get('strength', 'N/A'),
            corr_15m=f"{corr_15m.get('correlation', 0):.2f}",
            corr_15m_color=corr_15m.get('color', '#787b86'),
            corr_15m_strength=corr_15m.get('strength', 'N/A'),
            corr_1h=f"{corr_1h.get('correlation', 0):.2f}",
            corr_1h_color=corr_1h.get('color', '#787b86'),
            corr_1h_strength=corr_1h.get('strength', 'N/A'),

            lead_lag_text=lead_lag_text,
            divergence_gradient="#00C853, #FFD600, #FF9100, #FF1744",

            # Chart data
            es_realtime_data=self._format_ohlcv(es_realtime),
            es_realtime_volume=self._format_volume(es_realtime),
            btc_realtime_data=self._format_ohlcv(btc_realtime),
            btc_realtime_volume=self._format_volume(btc_realtime),
            es_historical_data=self._format_ohlcv(es_historical),
            btc_historical_data=self._format_ohlcv(btc_historical),
        )

        return html

    def save(self, html: str):
        """Save HTML to file"""
        import os
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(html)


# Quick test
if __name__ == '__main__':
    import time

    gen = DashboardGenerator()

    # Sample data
    now = int(time.time())
    es_data = [{'time': now - (30-i)*60, 'open': 6000+i, 'high': 6005+i, 'low': 5995+i, 'close': 6002+i, 'volume': 1000} for i in range(30)]
    btc_data = [{'time': now - (30-i)*60, 'open': 90000+i*10, 'high': 90050+i*10, 'low': 89950+i*10, 'close': 90020+i*10, 'volume': 100} for i in range(30)]

    corr = {
        '1m': {'correlation': 0.72, 'color': '#00C853', 'strength': 'strong'},
        '5m': {'correlation': 0.45, 'color': '#FFD600', 'strength': 'moderate'},
        '15m': {'correlation': 0.38, 'color': '#FF9100', 'strength': 'weak'},
        '1h': {'correlation': 0.55, 'color': '#FFD600', 'strength': 'moderate'},
    }

    html = gen.generate(es_data, btc_data, es_data, btc_data, corr, 'ESZ5', 'ES leads by 2 min')
    gen.save(html)
    print(f"Saved to {gen.output_path}")

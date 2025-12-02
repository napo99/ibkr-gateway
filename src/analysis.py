"""
Correlation and Lead/Lag Analysis
Improved with dynamic lag detection and significance testing
"""

import numpy as np
import pandas as pd
from scipy import stats
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class CorrelationResult:
    """Correlation analysis result"""
    correlation: float  # Pearson correlation coefficient
    p_value: float  # Statistical significance
    lead_lag: int  # Positive = ES leads, Negative = BTC leads
    lead_lag_corr: float  # Correlation at optimal lag
    strength: str  # 'strong', 'moderate', 'weak', 'none'

    @property
    def leader(self) -> str:
        if abs(self.lead_lag) < 1:
            return "SYNC"
        return "ES" if self.lead_lag > 0 else "BTC"

    @property
    def color(self) -> str:
        """Color code for visualization"""
        if self.correlation > 0.7:
            return "#00C853"  # Strong green
        elif self.correlation > 0.4:
            return "#FFD600"  # Yellow
        elif self.correlation > 0.2:
            return "#FF9100"  # Orange
        else:
            return "#FF1744"  # Red (divergence)

    def to_dict(self) -> dict:
        return {
            'correlation': round(self.correlation, 3),
            'p_value': round(self.p_value, 4),
            'lead_lag': self.lead_lag,
            'lead_lag_corr': round(self.lead_lag_corr, 3),
            'strength': self.strength,
            'leader': self.leader,
            'color': self.color
        }


def calculate_correlation(es_prices: np.ndarray, btc_prices: np.ndarray) -> CorrelationResult:
    """
    Calculate Pearson correlation between ES and BTC returns
    Uses returns (% change) not raw prices for better correlation
    """
    if len(es_prices) < 10 or len(btc_prices) < 10:
        return CorrelationResult(0, 1, 0, 0, 'none')

    # Align lengths
    min_len = min(len(es_prices), len(btc_prices))
    es = es_prices[-min_len:]
    btc = btc_prices[-min_len:]

    # Calculate returns
    es_returns = np.diff(es) / (es[:-1] + 1e-10)
    btc_returns = np.diff(btc) / (btc[:-1] + 1e-10)

    # Remove NaN/Inf
    mask = np.isfinite(es_returns) & np.isfinite(btc_returns)
    es_returns = es_returns[mask]
    btc_returns = btc_returns[mask]

    if len(es_returns) < 5:
        return CorrelationResult(0, 1, 0, 0, 'none')

    # Pearson correlation
    corr, p_value = stats.pearsonr(es_returns, btc_returns)

    # Handle NaN correlation
    if not np.isfinite(corr):
        corr = 0
        p_value = 1

    # Determine strength
    abs_corr = abs(corr)
    if abs_corr > 0.7:
        strength = 'strong'
    elif abs_corr > 0.4:
        strength = 'moderate'
    elif abs_corr > 0.2:
        strength = 'weak'
    else:
        strength = 'none'

    # Lead/Lag analysis via cross-correlation
    lead_lag, lead_lag_corr = calculate_lead_lag(es_returns, btc_returns)

    return CorrelationResult(
        correlation=corr,
        p_value=p_value,
        lead_lag=lead_lag,
        lead_lag_corr=lead_lag_corr,
        strength=strength
    )


def calculate_lead_lag(es_returns: np.ndarray, btc_returns: np.ndarray,
                       max_lag: int = None) -> Tuple[int, float]:
    """
    Calculate lead/lag relationship using cross-correlation

    Improved with:
    - Dynamic max_lag based on data length
    - Significance threshold for meaningful results
    - Better edge case handling

    Returns:
        (lag, correlation) where:
        - Positive lag = ES leads BTC by N periods
        - Negative lag = BTC leads ES by N periods
        - 0 = synchronized or no significant lead/lag
    """
    n = len(es_returns)

    # Dynamic max_lag: check up to 10% of data or 30 periods, whichever is smaller
    if max_lag is None:
        max_lag = min(max(n // 10, 5), 30)

    if n < max_lag * 2 + 1:
        return 0, 0.0

    # Normalize to zero mean, unit variance
    es_std = np.std(es_returns)
    btc_std = np.std(btc_returns)

    if es_std < 1e-10 or btc_std < 1e-10:
        return 0, 0.0

    es_norm = (es_returns - np.mean(es_returns)) / es_std
    btc_norm = (btc_returns - np.mean(btc_returns)) / btc_std

    # Cross-correlation at different lags
    correlations = []
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            # BTC leads: compare BTC[:-|lag|] with ES[|lag|:]
            abs_lag = abs(lag)
            if abs_lag >= len(btc_norm):
                continue
            corr_val = np.corrcoef(btc_norm[:-abs_lag], es_norm[abs_lag:])[0, 1]
        elif lag > 0:
            # ES leads: compare ES[:-lag] with BTC[lag:]
            if lag >= len(es_norm):
                continue
            corr_val = np.corrcoef(es_norm[:-lag], btc_norm[lag:])[0, 1]
        else:
            # Synchronous
            corr_val = np.corrcoef(es_norm, btc_norm)[0, 1]

        if np.isfinite(corr_val):
            correlations.append((lag, corr_val))

    if not correlations:
        return 0, 0.0

    # Find max absolute correlation
    best_lag, best_corr = max(correlations, key=lambda x: abs(x[1]))

    # Significance threshold: only report lead/lag if correlation at that lag
    # is significantly stronger than at lag 0
    sync_corr = next((c for l, c in correlations if l == 0), 0)

    # If the best correlation isn't meaningfully better than sync, report sync
    SIGNIFICANCE_THRESHOLD = 0.05  # 5% better correlation required
    if abs(best_corr) < 0.2:  # Correlation too weak to be meaningful
        return 0, sync_corr
    if abs(best_corr) - abs(sync_corr) < SIGNIFICANCE_THRESHOLD:
        return 0, sync_corr

    return best_lag, best_corr


def normalize_prices(es_prices: np.ndarray, btc_prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Normalize prices to 0-1 range for overlay comparison
    """
    es_range = np.max(es_prices) - np.min(es_prices)
    btc_range = np.max(btc_prices) - np.min(btc_prices)

    es_norm = (es_prices - np.min(es_prices)) / (es_range + 1e-10)
    btc_norm = (btc_prices - np.min(btc_prices)) / (btc_range + 1e-10)
    return es_norm, btc_norm


def calculate_divergence(es_prices: np.ndarray, btc_prices: np.ndarray,
                         window: int = 20) -> np.ndarray:
    """
    Calculate rolling divergence score
    High divergence = assets moving in opposite directions

    Returns array of divergence scores (0 = aligned, 1 = fully divergent)
    """
    if len(es_prices) < window or len(btc_prices) < window:
        return np.array([])

    min_len = min(len(es_prices), len(btc_prices))
    es = es_prices[-min_len:]
    btc = btc_prices[-min_len:]

    # Returns
    es_ret = np.diff(es) / (es[:-1] + 1e-10)
    btc_ret = np.diff(btc) / (btc[:-1] + 1e-10)

    # Rolling correlation
    divergence = np.zeros(len(es_ret) - window + 1)
    for i in range(len(divergence)):
        corr = np.corrcoef(es_ret[i:i+window], btc_ret[i:i+window])[0, 1]
        if np.isfinite(corr):
            divergence[i] = max(0, -corr)  # 0 when correlated, up to 1 when anti-correlated
        else:
            divergence[i] = 0

    return divergence


class MultiTimeframeAnalysis:
    """Analyze correlation across multiple timeframes"""

    TIMEFRAMES = {
        '1m': 1,
        '5m': 5,
        '15m': 15,
        '1h': 60
    }

    def __init__(self, es_df: pd.DataFrame, btc_df: pd.DataFrame):
        """
        Initialize with DataFrames
        Both must have 'timestamp' and 'close' columns
        """
        self.es_df = es_df.copy()
        self.btc_df = btc_df.copy()

        # Ensure timestamp is datetime (convert tz-aware to UTC for compatibility)
        if 'timestamp' in self.es_df.columns and not pd.api.types.is_datetime64_any_dtype(self.es_df['timestamp']):
            self.es_df['timestamp'] = pd.to_datetime(self.es_df['timestamp'], utc=True)
        if 'timestamp' in self.btc_df.columns and not pd.api.types.is_datetime64_any_dtype(self.btc_df['timestamp']):
            self.btc_df['timestamp'] = pd.to_datetime(self.btc_df['timestamp'], utc=True)

    def resample(self, df: pd.DataFrame, minutes: int) -> pd.DataFrame:
        """Resample to higher timeframe"""
        if minutes == 1:
            return df

        if 'timestamp' not in df.columns or len(df) == 0:
            return pd.DataFrame()

        df = df.set_index('timestamp')

        # Resample OHLCV properly
        agg_dict = {'close': 'last'}
        if 'open' in df.columns:
            agg_dict['open'] = 'first'
        if 'high' in df.columns:
            agg_dict['high'] = 'max'
        if 'low' in df.columns:
            agg_dict['low'] = 'min'
        if 'volume' in df.columns:
            agg_dict['volume'] = 'sum'

        resampled = df.resample(f'{minutes}min').agg(agg_dict).dropna().reset_index()
        return resampled

    def analyze_all(self) -> dict:
        """Calculate correlation for all timeframes"""
        results = {}

        for tf_name, minutes in self.TIMEFRAMES.items():
            try:
                es_resampled = self.resample(self.es_df, minutes)
                btc_resampled = self.resample(self.btc_df, minutes)

                if len(es_resampled) < 10 or len(btc_resampled) < 10:
                    results[tf_name] = CorrelationResult(0, 1, 0, 0, 'none').to_dict()
                    continue

                # Align by timestamp
                merged = pd.merge(
                    es_resampled[['timestamp', 'close']].rename(columns={'close': 'es_close'}),
                    btc_resampled[['timestamp', 'close']].rename(columns={'close': 'btc_close'}),
                    on='timestamp',
                    how='inner'
                )

                if len(merged) < 10:
                    results[tf_name] = CorrelationResult(0, 1, 0, 0, 'none').to_dict()
                    continue

                result = calculate_correlation(
                    merged['es_close'].values,
                    merged['btc_close'].values
                )
                results[tf_name] = result.to_dict()

            except Exception as e:
                print(f"[ANALYSIS] Error calculating {tf_name} correlation: {e}")
                results[tf_name] = CorrelationResult(0, 1, 0, 0, 'none').to_dict()

        return results


# Quick test
if __name__ == '__main__':
    # Generate synthetic data
    np.random.seed(42)
    n = 100

    # ES with some trend
    es_prices = 6000 + np.cumsum(np.random.randn(n) * 2)

    # BTC correlated but with lag and noise
    btc_prices = 90000 + np.cumsum(np.random.randn(n) * 500 + np.roll(np.diff(es_prices, prepend=es_prices[0]) * 50, 2))

    result = calculate_correlation(es_prices, btc_prices)
    print(f"Correlation: {result.correlation:.3f}")
    print(f"Strength: {result.strength}")
    print(f"Lead/Lag: {result.lead_lag} ({result.leader} leads)")
    print(f"Color: {result.color}")

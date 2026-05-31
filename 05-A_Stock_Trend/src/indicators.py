"""
SuperTrend — TradingView Pine v4 移植（ATR 趋势跟踪）

接受 OHLCV DataFrame，返回带 SuperTrend 列的新 DataFrame。
"""

import numpy as np
import pandas as pd


def supertrend(
    df: pd.DataFrame,
    atr_period: int = 10,
    multiplier: float = 3.0,
    use_wilder_atr: bool = True,
) -> pd.DataFrame:
    """
    Parameters
    ----------
    df            : OHLCV DataFrame (Open, High, Low, Close, Volume)
    atr_period    : ATR 周期（默认 10）
    multiplier    : ATR 带宽倍数（默认 3.0）
    use_wilder_atr: True → Wilder ATR；False → SMA(TR)

    Returns
    -------
    DataFrame，新增列: atr, up_band, dn_band, trend, buy_signal, sell_signal
    """
    df = df.copy()
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    src = (high + low) / 2

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    if use_wilder_atr:
        atr = tr.ewm(alpha=1 / atr_period, min_periods=atr_period, adjust=False).mean()
    else:
        atr = tr.rolling(atr_period).mean()

    df["atr"] = atr

    n = len(df)
    up_band = np.full(n, np.nan)
    dn_band = np.full(n, np.nan)
    trend = np.full(n, np.nan)

    src_arr = src.to_numpy()
    close_arr = close.to_numpy()
    atr_arr = atr.to_numpy()

    for i in range(n):
        if np.isnan(atr_arr[i]):
            trend[i] = 1
            continue

        raw_up = src_arr[i] - multiplier * atr_arr[i]
        raw_dn = src_arr[i] + multiplier * atr_arr[i]

        prev_up = up_band[i - 1] if i > 0 and not np.isnan(up_band[i - 1]) else raw_up
        prev_dn = dn_band[i - 1] if i > 0 and not np.isnan(dn_band[i - 1]) else raw_dn
        prev_close_val = close_arr[i - 1] if i > 0 else close_arr[i]
        prev_trend = trend[i - 1] if i > 0 and not np.isnan(trend[i - 1]) else 1

        up_band[i] = max(raw_up, prev_up) if prev_close_val > prev_up else raw_up
        dn_band[i] = min(raw_dn, prev_dn) if prev_close_val < prev_dn else raw_dn

        if prev_trend == -1 and close_arr[i] > dn_band[i - 1] if i > 0 else False:
            trend[i] = 1
        elif prev_trend == 1 and close_arr[i] < up_band[i - 1] if i > 0 else False:
            trend[i] = -1
        else:
            trend[i] = prev_trend

    df["up_band"] = up_band
    df["dn_band"] = dn_band
    df["trend"] = trend
    df["buy_signal"] = (df["trend"] == 1) & (df["trend"].shift(1) == -1)
    df["sell_signal"] = (df["trend"] == -1) & (df["trend"].shift(1) == 1)

    return df

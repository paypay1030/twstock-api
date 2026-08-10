"""
技術指標計算服務

根據 K 線 DataFrame 計算：
  MA5 / MA10 / MA20 / MA60 / MA240
  RSI(14)
  MACD (EMA12, EMA26, Signal9)
  KD 隨機指標 (9日 RSV → 2/3 smoothing)
  Bollinger Bands (20日, ±2σ)

所有計算均純用 pandas + numpy，不依賴第三方 ta 函式庫。
"""
import math
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from app.utils.safe_convert import safe_float

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, period: int) -> pd.Series:
    """指數移動平均（EMA），使用 pandas ewm 標準實作"""
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    """簡單移動平均（SMA）"""
    return series.rolling(window=period).mean()


def _to_val(v) -> float | None:
    """pandas / numpy 值轉 Python float，NaN/inf → None"""
    f = safe_float(v, default=None)
    if f is None:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 4)


def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    輸入：stock_fetcher.get_stock_history() 回傳的 DataFrame
          欄位：Open / High / Low / Close / Volume（index = date）
    輸出：符合前端 TechIndicators 介面的 dict
    """
    try:
        close  = df['Close'].astype(float)
        high   = df['High'].astype(float)
        low    = df['Low'].astype(float)
        volume = df['Volume'].astype(float)
    except Exception as e:
        logger.error(f"[indicators] DataFrame 欄位讀取失敗: {e}")
        return _empty_result()

    n = len(close)
    if n < 5:
        logger.warning(f"[indicators] 資料不足（{n} 行），無法計算技術指標")
        return _empty_result()

    # ── 均線 ─────────────────────────────────────────────────
    ma5   = _sma(close, 5)
    ma10  = _sma(close, 10)
    ma20  = _sma(close, 20)
    ma60  = _sma(close, 60)
    ma240 = _sma(close, 240)

    # ── RSI (14) ─────────────────────────────────────────────
    delta  = close.diff()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.ewm(com=13, adjust=False).mean()
    avg_l  = loss.ewm(com=13, adjust=False).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    rsi14  = 100 - (100 / (1 + rs))

    # ── MACD (12, 26, 9) ─────────────────────────────────────
    ema12  = _ema(close, 12)
    ema26  = _ema(close, 26)
    dif    = ema12 - ema26        # DIF（快線）
    dea    = _ema(dif, 9)         # DEA / Signal（慢線）
    hist   = (dif - dea) * 2      # MACD 柱狀圖（台灣慣例 ×2）

    # ── KD 隨機指標 (9日 RSV, 2/3 smoothing) ─────────────────
    period_kd = 9
    low_min  = low.rolling(period_kd).min()
    high_max = high.rolling(period_kd).max()
    denom    = (high_max - low_min).replace(0, np.nan)
    rsv      = (close - low_min) / denom * 100

    k_vals = []
    d_vals = []
    prev_k = 50.0
    prev_d = 50.0
    for rsv_val in rsv:
        if pd.isna(rsv_val):
            k_vals.append(np.nan)
            d_vals.append(np.nan)
        else:
            k = prev_k * 2/3 + rsv_val * 1/3
            d = prev_d * 2/3 + k * 1/3
            k_vals.append(k)
            d_vals.append(d)
            prev_k, prev_d = k, d

    k_series = pd.Series(k_vals, index=close.index)
    d_series = pd.Series(d_vals, index=close.index)
    j_series = k_series * 3 - d_series * 2

    # ── Bollinger Bands (20日, ±2σ) ──────────────────────────
    bb_mid   = _sma(close, 20)
    bb_std   = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    # ── 趨勢判斷（MA 多頭/空頭排列）─────────────────────────
    trend, trend_label = _calc_trend(
        close.iloc[-1],
        ma5.iloc[-1], ma20.iloc[-1], ma60.iloc[-1]
    )

    # ── 成交量均線 ────────────────────────────────────────────
    vol_ma5  = _sma(volume, 5)
    vol_ma20 = _sma(volume, 20)

    return {
        # 均線
        "ma5":   _to_val(ma5.iloc[-1]),
        "ma10":  _to_val(ma10.iloc[-1]),
        "ma20":  _to_val(ma20.iloc[-1]),
        "ma60":  _to_val(ma60.iloc[-1]),
        "ma240": _to_val(ma240.iloc[-1]),
        # RSI
        "rsi": _to_val(rsi14.iloc[-1]),
        # MACD
        "macd": {
            "dif":  _to_val(dif.iloc[-1]),
            "dea":  _to_val(dea.iloc[-1]),
            "hist": _to_val(hist.iloc[-1]),
        },
        # KD
        "kd": {
            "k": _to_val(k_series.iloc[-1]),
            "d": _to_val(d_series.iloc[-1]),
            "j": _to_val(j_series.iloc[-1]),
        },
        # 布林通道
        "bollinger": {
            "upper":  _to_val(bb_upper.iloc[-1]),
            "middle": _to_val(bb_mid.iloc[-1]),
            "lower":  _to_val(bb_lower.iloc[-1]),
        },
        # 成交量
        "volume": {
            "current": _to_val(volume.iloc[-1]),
            "ma5":     _to_val(vol_ma5.iloc[-1]),
            "ma20":    _to_val(vol_ma20.iloc[-1]),
        },
        # 趨勢
        "trend":       trend,
        "trend_label": trend_label,
        # 元資料
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }


def _calc_trend(price: float, ma5, ma20, ma60) -> tuple[str, str]:
    """根據 MA5 / MA20 / MA60 排列判斷趨勢"""
    try:
        p, m5, m20, m60 = float(price), float(ma5), float(ma20), float(ma60)
        if any(math.isnan(v) for v in [p, m5, m20, m60]):
            return "neutral", "資料不足"
        if p > m5 > m20 > m60:
            return "bull", "多頭排列"
        if p < m5 < m20 < m60:
            return "bear", "空頭排列"
        if p > m20:
            return "bull", "短線偏多"
        if p < m20:
            return "bear", "短線偏空"
        return "neutral", "盤整"
    except Exception:
        return "neutral", "盤整"


def _empty_result() -> dict:
    """資料不足時回傳空結構（所有數值 None）"""
    return {
        "ma5": None, "ma10": None, "ma20": None, "ma60": None, "ma240": None,
        "rsi": None,
        "macd":      {"dif": None, "dea": None, "hist": None},
        "kd":        {"k": None, "d": None, "j": None},
        "bollinger": {"upper": None, "middle": None, "lower": None},
        "volume":    {"current": None, "ma5": None, "ma20": None},
        "trend": "neutral", "trend_label": "資料不足",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

"""
安全型別轉換工具

避免因 Yahoo Finance 資料含 NaN、None、inf 導致的轉型錯誤。
ETF 因成立時間短、欄位不完整，特別容易出現這類問題。

設計原則：
  - safe_float / safe_int：接受任何輸入，異常值回傳 default
  - default 可為 None（供 JSON 回傳 null，前端顯示 --）
  - clean_df：專門處理 DataFrame，inf→NaN，不強制填 0
  - safe_series_to_int：整個 Series 安全轉 int64
  - safe_score：確保分數在 [0, 100] 且非 NaN（供 Pydantic 驗證）
"""
import math
import numpy as np
import pandas as pd
from typing import Any, Optional, Union


def safe_float(
    value: Any,
    default: Union[float, None] = 0.0,
) -> Optional[float]:
    """
    安全轉換為 float，任何異常值（None/NaN/inf）一律回傳 default。
    default 可傳入 None，此時異常值會回傳 None（JSON 序列化為 null）。
    """
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def safe_int(
    value: Any,
    default: int = 0,
) -> int:
    """
    安全轉換為 int，任何異常值一律回傳 default。
    先透過 safe_float 消除 NaN/inf，再轉 int。
    """
    f = safe_float(value, default=float(default))
    if f is None:
        return default
    return int(f)


def safe_score(value: Any) -> float:
    """
    專門用於 Pydantic score 欄位（ge=0, le=100）。
    確保回傳值一定是 [0.0, 100.0] 內的有效 float，
    避免 NaN/inf 導致 Pydantic ValidationError。
    """
    f = safe_float(value, default=0.0)
    if f is None:
        return 0.0
    return max(0.0, min(100.0, f))


def safe_price(value: Any, fallback: float = 0.0) -> float:
    """
    安全轉換為價格（float），NaN/inf 回傳 fallback（而非 0 以免誤用）。
    """
    f = safe_float(value, default=None)
    return f if f is not None and f > 0 else fallback


def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    清理 DataFrame：
      1. 將所有數值欄位的 inf / -inf 替換為 NaN
    注意：刻意不 fillna(0)，保留 NaN 以便後續 dropna() 邏輯正確運作。
    """
    df = df.copy()
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
    return df


def safe_series_to_int(
    series: pd.Series,
    default: int = 0,
) -> pd.Series:
    """
    將整個 Series 安全轉換為 int64。
    NaN / inf 先替換為 default，再轉型。
    避免 .astype(int) 在含 NaN 時拋出 ValueError：
      「Cannot convert non-finite values (NA or inf) to integer」
    """
    cleaned = series.replace([np.inf, -np.inf], np.nan).fillna(default)
    return cleaned.astype(np.int64)

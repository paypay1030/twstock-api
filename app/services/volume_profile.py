"""
Volume Profile 成交量密集區計算

將近 3 年收盤價分成 N 個等寬區間（預設 60 格）
統計每格累積成交量，找出籌碼密集位置
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from app.core.config import get_settings
from app.utils.safe_convert import safe_series_to_int, clean_df

settings = get_settings()


@dataclass
class VPZone:
    """成交量密集區"""
    price_low: float
    price_high: float
    center: float
    volume_ratio: float          # 佔總量百分比
    is_strong: bool              # 是否為強密集區


def calculate_volume_profile(
    df: pd.DataFrame,
    buckets: int | None = None
) -> list[VPZone]:
    """
    計算 Volume Profile

    Args:
        df: 含 Close, Volume 欄位的 DataFrame
        buckets: 分桶數，None 則用設定值

    Returns:
        依 volume_ratio 由大到小排序的密集區清單
    """
    n = buckets or settings.volume_profile_buckets

    # ── 防呆：清理 inf / NaN，避免 ETF 資料異常值導致轉型錯誤 ──
    df = clean_df(df)

    # 過濾掉 Close / Volume 異常的行
    df = df[df["Close"] > 0].copy()
    if df.empty:
        return []

    price_min = df["Close"].min()
    price_max = df["Close"].max()
    bucket_size = (price_max - price_min) / n

    if bucket_size <= 0:
        return []

    # 每根 K 棒依收盤價歸入對應格子
    # 使用 safe_series_to_int 避免 NaN → astype(int) 拋 ValueError
    raw_bucket = (df["Close"] - price_min) / bucket_size
    df = df.copy()
    df["bucket"] = safe_series_to_int(raw_bucket).clip(0, n - 1)

    # 累積每格成交量
    grouped = df.groupby("bucket")["Volume"].sum()
    total_volume = grouped.sum()
    if total_volume == 0:
        return []

    zones: list[VPZone] = []
    for bucket_idx, vol in grouped.items():
        ratio = vol / total_volume
        if ratio < settings.vp_threshold_normal:
            continue  # 量太小，忽略

        low  = round(price_min + bucket_idx * bucket_size, 2)
        high = round(low + bucket_size, 2)
        center = round((low + high) / 2, 2)

        zones.append(VPZone(
            price_low=low,
            price_high=high,
            center=center,
            volume_ratio=round(ratio, 4),
            is_strong=(ratio >= settings.vp_threshold_strong)
        ))

    # 由量大到小排序
    zones.sort(key=lambda z: z.volume_ratio, reverse=True)
    return zones


def get_vp_score(candidate_price: float, zones: list[VPZone]) -> float:
    """
    計算候選價位的 Volume Profile 得分（0~1）
    在密集區內且越強，分數越高
    """
    for zone in zones:
        if zone.price_low <= candidate_price <= zone.price_high:
            base = zone.volume_ratio / settings.vp_threshold_strong
            return min(base, 1.0) * (1.2 if zone.is_strong else 1.0)
    return 0.0


def find_vp_support_resistance(
    current_price: float,
    zones: list[VPZone]
) -> tuple[list[VPZone], list[VPZone]]:
    """
    依現價將密集區分為支撐（下方）與壓力（上方）
    """
    support  = [z for z in zones if z.center < current_price]
    resist   = [z for z in zones if z.center > current_price]

    # 支撐：依中心價由近（大）到遠（小）排序
    support.sort(key=lambda z: z.center, reverse=True)
    # 壓力：依中心價由近（小）到遠（大）排序
    resist.sort(key=lambda z: z.center)

    return support, resist

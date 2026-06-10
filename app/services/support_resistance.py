"""
支撐壓力主計算服務

整合四個來源：
  1. Volume Profile（40%）
  2. 歷史前高前低（30%）
  3. MA60 季線（15%）
  4. MA240 年線（10%）
  5. MA20 月線（5%）

最終輸出：第一/第二支撐、第一/第二壓力、停損建議
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from app.core.config import get_settings
from app.services.volume_profile import (
    calculate_volume_profile, get_vp_score,
    find_vp_support_resistance, VPZone
)
from app.models.analysis import SRLevel, SupportResistanceResult
from app.utils.price_utils import round_to_tick, pct_diff

settings = get_settings()


# ── 歷史前高前低 ─────────────────────────────────────────────

@dataclass
class HLPoint:
    price: float
    touch_count: int   # 被碰觸並反彈次數
    timeframe: str     # "1m" / "3m" / "1y"
    weight: float      # 時間框架權重


def _find_pivot_highs(series: pd.Series, window: int = 5) -> pd.Series:
    """找局部高點：左右各 window 根都比它低"""
    highs = []
    for i in range(window, len(series) - window):
        if series.iloc[i] == series.iloc[i-window:i+window+1].max():
            highs.append((series.index[i], series.iloc[i]))
    return highs


def _find_pivot_lows(series: pd.Series, window: int = 5) -> pd.Series:
    """找局部低點：左右各 window 根都比它高"""
    lows = []
    for i in range(window, len(series) - window):
        if series.iloc[i] == series.iloc[i-window:i+window+1].min():
            lows.append((series.index[i], series.iloc[i]))
    return lows


def _count_touches(price: float, df: pd.DataFrame, tolerance: float = 0.015) -> int:
    """
    計算價格被碰觸並反彈的次數
    tolerance = 1.5%（在此範圍內視為觸及）
    """
    count = 0
    close = df["Close"].values
    for i in range(1, len(close) - 1):
        if abs(close[i] - price) / price <= tolerance:
            # 確認碰觸後有反彈（前後方向不同）
            came_from_above = close[i-1] > price
            went_back_above = close[i+1] > price
            if came_from_above == went_back_above:
                count += 1
    return count


def get_historical_levels(df: pd.DataFrame, current_price: float) -> list[HLPoint]:
    """
    多時間框架掃描前高前低
    """
    n = len(df)
    points: list[HLPoint] = []

    configs = [
        ("1m",  min(20, n),  0.8),
        ("3m",  min(60, n),  1.0),
        ("1y",  min(240, n), 1.2),
    ]

    for timeframe, bars, tw in configs:
        sub = df.iloc[-bars:]

        for _, price in _find_pivot_highs(sub["High"]):
            touches = _count_touches(price, sub)
            if touches >= 2:
                points.append(HLPoint(
                    price=round(price, 2),
                    touch_count=touches,
                    timeframe=timeframe,
                    weight=tw
                ))

        for _, price in _find_pivot_lows(sub["Low"]):
            touches = _count_touches(price, sub)
            if touches >= 2:
                points.append(HLPoint(
                    price=round(price, 2),
                    touch_count=touches,
                    timeframe=timeframe,
                    weight=tw
                ))

    return points


def _hl_score(candidate: float, points: list[HLPoint]) -> float:
    """計算候選價位的歷史高低點得分（0~1）"""
    best = 0.0
    for p in points:
        if abs(p.price - candidate) / candidate <= 0.02:  # 2% 容忍
            score = min(p.touch_count / 4.0, 1.0) * (p.weight / 1.2)
            best = max(best, score)
    return best


# ── 均線得分 ──────────────────────────────────────────────────

def _ma_score(candidate: float, ma_val: float | None,
              current: float, weight: float) -> float:
    """如果候選價位在均線 ±3% 內，給對應權重的分"""
    if ma_val is None or np.isnan(ma_val):
        return 0.0
    if abs(candidate - ma_val) / current <= settings.ma_proximity_pct:
        return weight
    return 0.0


# ── 候選位合併 ────────────────────────────────────────────────

def _merge_candidates(prices: list[float], tolerance: float = 0.02) -> list[float]:
    """
    將距離相近（2%以內）的候選位合併為一個（取平均）
    """
    if not prices:
        return []
    prices = sorted(prices)
    merged = [prices[0]]
    for p in prices[1:]:
        if abs(p - merged[-1]) / merged[-1] <= tolerance:
            merged[-1] = round((merged[-1] + p) / 2, 2)
        else:
            merged.append(p)
    return merged


# ── 主函數 ────────────────────────────────────────────────────

def calculate_sr(df: pd.DataFrame, current_price: float) -> SupportResistanceResult:
    """
    主計算函數：整合所有來源，輸出標準化 SupportResistanceResult
    """
    # 1. Volume Profile
    vp_zones = calculate_volume_profile(df)
    vp_support, vp_resist = find_vp_support_resistance(current_price, vp_zones)

    # 2. 歷史前高前低
    hl_points = get_historical_levels(df, current_price)

    # 3. 均線（取最新一筆）
    ma20  = _safe_ma(df, "MA20")
    ma60  = _safe_ma(df, "MA60")
    ma240 = _safe_ma(df, "MA240")

    # 4. 建立候選位清單（支撐：現價以下；壓力：現價以上）
    support_candidates  = _gather_candidates(
        current_price, vp_support, hl_points,
        [ma20, ma60, ma240], direction="support"
    )
    resist_candidates = _gather_candidates(
        current_price, vp_resist, hl_points,
        [ma20, ma60, ma240], direction="resist"
    )

    # 5. 評分
    support_levels  = _score_and_rank(
        support_candidates, current_price, vp_zones,
        hl_points, ma20, ma60, ma240, direction="support"
    )
    resist_levels = _score_and_rank(
        resist_candidates, current_price, vp_zones,
        hl_points, ma20, ma60, ma240, direction="resist"
    )

    # 6. 停損：強支撐下緣往下一個 tick 的 -2%
    if support_levels:
        strong = next((s for s in support_levels if s.strength == "strong"),
                      support_levels[-1])
        stop_loss = round_to_tick(strong.range_low * 0.98)
    else:
        stop_loss = round_to_tick(current_price * 0.93)

    return SupportResistanceResult(
        support_levels=support_levels[:2],
        resistance_levels=resist_levels[:2],
        stop_loss=stop_loss
    )


# ── 私有輔助 ──────────────────────────────────────────────────

def _safe_ma(df: pd.DataFrame, col: str) -> float | None:
    try:
        val = df[col].dropna().iloc[-1]
        return float(val) if not np.isnan(val) else None
    except Exception:
        return None


def _gather_candidates(
    current: float,
    vp_zones: list,
    hl_points: list,
    mas: list,
    direction: str
) -> list[float]:
    prices = []

    for z in vp_zones[:8]:
        prices.append(z.center)

    for p in hl_points:
        if direction == "support" and p.price < current:
            prices.append(p.price)
        elif direction == "resist" and p.price > current:
            prices.append(p.price)

    for ma in mas:
        if ma is None:
            continue
        if direction == "support" and ma < current:
            prices.append(ma)
        elif direction == "resist" and ma > current:
            prices.append(ma)

    merged = _merge_candidates(prices)

    if direction == "support":
        merged = [p for p in merged if p < current]
        merged.sort(reverse=True)  # 由近到遠
    else:
        merged = [p for p in merged if p > current]
        merged.sort()              # 由近到遠

    return merged[:6]


def _score_and_rank(
    candidates: list[float],
    current: float,
    vp_zones: list,
    hl_points: list,
    ma20, ma60, ma240,
    direction: str
) -> list[SRLevel]:
    results = []
    for rank, price in enumerate(candidates, 1):
        sources = []

        vp_s = get_vp_score(price, vp_zones)
        vp_pts = vp_s * settings.weight_volume_profile * 100
        if vp_s > 0:
            sources.append("volume_profile")

        hl_s = _hl_score(price, hl_points)
        hl_pts = hl_s * settings.weight_historical_hl * 100
        if hl_s > 0:
            sources.append("historical_hl")

        ma20_pts  = _ma_score(price, ma20,  current, settings.weight_ma20  * 100)
        ma60_pts  = _ma_score(price, ma60,  current, settings.weight_ma60  * 100)
        ma240_pts = _ma_score(price, ma240, current, settings.weight_ma240 * 100)

        if ma20_pts  > 0: sources.append("ma20")
        if ma60_pts  > 0: sources.append("ma60")
        if ma240_pts > 0: sources.append("ma240")

        total_score = vp_pts + hl_pts + ma20_pts + ma60_pts + ma240_pts

        if total_score < settings.sr_score_normal:
            continue  # 弱位，不顯示

        strength = "strong" if total_score >= settings.sr_score_strong else "normal"
        prefix = "第一" if rank == 1 else "第二"

        if direction == "support":
            label = f"{prefix}支撐" + ("（強）" if strength == "strong" else "")
        else:
            label = f"{prefix}壓力" + ("（強）" if strength == "strong" else "")

        margin = price * 0.01
        results.append(SRLevel(
            rank=rank,
            range_low=round(price - margin, 2),
            range_high=round(price + margin, 2),
            label=label,
            strength=strength,
            score=round(total_score, 1),
            sources=sources
        ))

    return results

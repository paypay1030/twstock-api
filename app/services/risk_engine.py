"""
風險等級計算引擎

三因子加權：
  成本距離（40%）+ 支撐距離（35%）+ ATR 波動率（25%）
"""
import numpy as np
import pandas as pd
from app.core.config import get_settings
from app.models.analysis import RiskResult, SignalResult, SRLevel

settings = get_settings()


def calculate_signal(
    current_price: float,
    support_levels: list[SRLevel],
    resistance_levels: list[SRLevel],
    stop_loss: float
) -> SignalResult:
    """
    計算投資燈號

    閾值（可配置）：
      距壓力 ≤ SIGNAL_RESIST_NEAR → 橘燈
      距壓力 ≤ SIGNAL_RESIST_MID  → 黃燈
      距支撐 ≤ SIGNAL_SUPPORT_NEAR → 綠燈
      跌破支撐或停損 → 紅燈
    """
    # 取第一壓力下緣 / 第一支撐上緣
    nearest_resist  = resistance_levels[0].range_low  if resistance_levels  else None
    nearest_support = support_levels[0].range_high    if support_levels     else None

    # 紅燈：跌破停損或跌破第一支撐
    if current_price <= stop_loss:
        return SignalResult(
            color="red", emoji="🔴", label="紅燈",
            desc="跌破停損，風險升高"
        )
    if nearest_support and current_price <= nearest_support:
        return SignalResult(
            color="red", emoji="🔴", label="紅燈",
            desc="跌破支撐，風險升高"
        )

    # 距壓力計算
    if nearest_resist:
        to_resist = (nearest_resist - current_price) / current_price

        if to_resist <= 0:
            return SignalResult(
                color="orange", emoji="🟠", label="橘燈",
                desc="進入壓力區，考慮減碼"
            )
        if to_resist <= settings.signal_resist_near:
            return SignalResult(
                color="orange", emoji="🟠", label="橘燈",
                desc=f"接近壓力區（差 {to_resist*100:.1f}%），注意風險"
            )
        if to_resist <= settings.signal_resist_mid:
            return SignalResult(
                color="yellow", emoji="🟡", label="黃燈",
                desc="區間整理，持續觀察"
            )

    # 距支撐計算 → 綠燈
    if nearest_support:
        to_support = (current_price - nearest_support) / current_price
        if to_support <= settings.signal_support_near:
            return SignalResult(
                color="green", emoji="🟢", label="綠燈",
                desc=f"接近支撐區（差 {to_support*100:.1f}%），可考慮布局"
            )

    # 預設黃燈
    return SignalResult(
        color="yellow", emoji="🟡", label="黃燈",
        desc="區間整理，持續觀察"
    )


def calculate_risk(
    current_price: float,
    cost: float | None,
    support_levels: list[SRLevel],
    df: pd.DataFrame
) -> RiskResult:
    """
    計算風險等級（三因子加權）
    cost = None 時，成本距離因子以 0 計算
    """
    # ── 因子一：成本距離（40%）────────────────────────────────
    if cost and cost > 0:
        pnl_pct = (current_price - cost) / cost
        # 損益越差，風險越高
        # 損益 > 15% → 低風險(0分)
        # 損益 -5% ~ 15% → 中風險(50分)
        # 損益 < -5% → 高風險(100分)
        if pnl_pct > 0.15:
            cost_score = 10.0
        elif pnl_pct >= -0.05:
            cost_score = 50.0
        else:
            # 越深套，分數越高（最高 100）
            cost_score = min(50.0 + abs(pnl_pct + 0.05) * 500, 100.0)
    else:
        cost_score = 50.0  # 無成本資訊，預設中等

    # ── 因子二：距支撐距離（35%）─────────────────────────────
    if support_levels:
        nearest_sup = support_levels[0].range_high
        to_sup_pct = (current_price - nearest_sup) / current_price
        # 距支撐越近，風險越低；跌破支撐風險最高
        if to_sup_pct < 0:
            sup_score = 100.0
        elif to_sup_pct < 0.03:
            sup_score = 20.0   # 接近支撐，低風險
        elif to_sup_pct < 0.08:
            sup_score = 50.0
        else:
            sup_score = 70.0
    else:
        sup_score = 60.0

    # ── 因子三：ATR 波動率（25%）─────────────────────────────
    try:
        from app.utils.safe_convert import safe_float as _sf
        raw_atr = df["ATR14"].dropna()
        atr_val = _sf(raw_atr.iloc[-1] if not raw_atr.empty else None, default=None)
        if atr_val is None or atr_val <= 0:
            raise ValueError("ATR unavailable")
        atr_pct = atr_val / current_price
        if atr_pct < settings.atr_low_threshold:
            atr_score = 20.0
        elif atr_pct < settings.atr_high_threshold:
            atr_score = 50.0
        else:
            atr_score = 90.0
    except Exception:
        atr_score = 50.0

    # ── 加權總分 ──────────────────────────────────────────────
    total = (
        cost_score    * settings.risk_weight_cost_dist +
        sup_score     * settings.risk_weight_support_dist +
        atr_score     * settings.risk_weight_atr
    )

    if total < 35:
        level, label = "low", "低"
    elif total < 65:
        level, label = "medium", "中"
    else:
        level, label = "high", "高"

    return RiskResult(
        level=level,
        label=label,
        score=round(total, 1),
        cost_dist_score=round(cost_score, 1),
        support_dist_score=round(sup_score, 1),
        atr_score=round(atr_score, 1)
    )

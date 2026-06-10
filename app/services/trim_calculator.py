"""
智慧減碼試算服務
"""
import math
from app.core.config import get_settings
from app.models.analysis import TrimSuggestion, UnstuckEvaluation, SRLevel

settings = get_settings()


def _shares_to_lots(shares: int) -> int:
    return shares // 1000


def calc_trim(
    shares: int,
    current_price: float,
    pct: float,
    trigger: str,
    basis: str = "shares",   # "shares" | "value"
    cost: float | None = None
) -> TrimSuggestion:
    """
    計算單次減碼結果

    basis="shares" → 依股數計算
    basis="value"  → 依市值計算
    """
    if basis == "value" and cost:
        total_value = shares * current_price
        sell_value  = total_value * pct
        sell_shares = math.floor(sell_value / current_price)
    else:
        sell_shares = math.floor(shares * pct)

    sell_shares  = min(sell_shares, shares)
    remain       = shares - sell_shares
    recover      = round(sell_shares * current_price, 0)
    remain_value = round(remain * current_price, 0)

    return TrimSuggestion(
        trigger=trigger,
        pct=round(pct * 100, 1),
        sell_shares=sell_shares,
        sell_lots=_shares_to_lots(sell_shares),
        remain_shares=remain,
        recover_amount=recover,
        remain_value=remain_value
    )


def get_trim_suggestion(
    signal_color: str,
    shares: int,
    current_price: float,
    resistance_levels: list[SRLevel],
    custom_rules: dict | None = None,
    basis: str = "shares"
) -> TrimSuggestion | None:
    """
    依燈號自動選擇減碼比例並計算
    custom_rules 可覆寫預設百分比
    """
    rules = {
        "near_resist":    custom_rules.get("near_resist",    settings.trim_rule_near_resist)    if custom_rules else settings.trim_rule_near_resist,
        "in_resist":      custom_rules.get("in_resist",      settings.trim_rule_in_resist)      if custom_rules else settings.trim_rule_in_resist,
        "fail_breakout":  custom_rules.get("fail_breakout",  settings.trim_rule_fail_breakout)  if custom_rules else settings.trim_rule_fail_breakout,
        "break_support":  custom_rules.get("break_support",  settings.trim_rule_break_support)  if custom_rules else settings.trim_rule_break_support,
    }

    if signal_color == "red":
        return calc_trim(shares, current_price, rules["break_support"],
                         "跌破支撐，建議全部出清", basis)

    if signal_color == "orange":
        nearest_resist = resistance_levels[0].range_low if resistance_levels else 0
        if current_price >= nearest_resist:
            return calc_trim(shares, current_price, rules["in_resist"],
                             "進入壓力區，建議減碼 30%", basis)
        else:
            return calc_trim(shares, current_price, rules["near_resist"],
                             "接近壓力區，建議減碼 20%", basis)

    return None  # 綠燈/黃燈不建議減碼


def get_unstuck_evaluation(
    shares: int,
    cost: float,
    current_price: float,
) -> UnstuckEvaluation | None:
    """
    解套模式：當持股虧損時提供分段減碼建議
    """
    if current_price >= cost:
        return None  # 未虧損，不啟動

    unrealized_loss     = round((current_price - cost) * shares, 0)
    unrealized_loss_pct = round((current_price - cost) / cost * 100, 2)

    # 第一段：減碼 30%，回收部分資金
    stage1 = calc_trim(shares, current_price, 0.30,
                        "第一段：減少損失，回收 30% 資金")

    # 第二段：若持續下跌再減 30%（以剩餘股數計算）
    stage2 = calc_trim(stage1.remain_shares, current_price, 0.30,
                        "第二段：再次下跌時，再減 30%")

    loss_pct_abs = abs(unrealized_loss_pct)
    if loss_pct_abs < 5:
        evaluation = f"目前小幅虧損 {loss_pct_abs:.1f}%，建議耐心等待支撐反彈，非緊急情況。"
    elif loss_pct_abs < 15:
        evaluation = f"虧損 {loss_pct_abs:.1f}%，建議考慮分批減碼，降低持倉風險，避免擴大損失。"
    else:
        evaluation = f"虧損幅度較深（{loss_pct_abs:.1f}%），建議評估停損，保留資金尋找下一個機會。"

    return UnstuckEvaluation(
        cost=cost,
        current_price=current_price,
        unrealized_loss=unrealized_loss,
        unrealized_loss_pct=unrealized_loss_pct,
        breakeven_price=cost,
        stage1_reduce=stage1,
        stage2_reduce=stage2,
        evaluation=evaluation
    )

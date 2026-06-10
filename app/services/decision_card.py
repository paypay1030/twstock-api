"""
懶人決策卡生成服務

整合燈號、支撐壓力、風險等級，輸出完整決策卡 JSON
"""
from app.models.analysis import (
    DecisionCard, TriggerAction, SignalResult, RiskResult,
    SupportResistanceResult
)
from app.services.trim_calculator import get_trim_suggestion, get_unstuck_evaluation
from app.utils.price_utils import round_to_tick

# ── 原因文字模板 ──────────────────────────────────────────────

REASON_TEMPLATES = {
    "green_no_hold": (
        "現價 {price} 接近支撐區 {support}，"
        "風險報酬比相對有利，可考慮分批布局。"
        "注意：此為機率評估，非保證獲利。"
    ),
    "green_hold": (
        "現價 {price} 接近支撐區 {support}，"
        "持股尚有支撐，可考慮適量加碼，"
        "但請注意控制整體部位風險。"
    ),
    "yellow_hold": (
        "目前位於支撐壓力中間段，趨勢尚未明朗，"
        "建議續抱觀察，等待方向確立後再決定操作。"
    ),
    "yellow_no_hold": (
        "目前位於整理區間，尚無明確買進或賣出訊號，"
        "建議觀察等待，不追高、不搶反彈。"
    ),
    "orange_near": (
        "現價 {price} 接近壓力區 {resist}，"
        "上漲空間縮小，風險報酬比下降，"
        "建議留意，可考慮分批減碼。"
    ),
    "orange_in": (
        "現價已進入壓力區 {resist}，"
        "短期反壓增加，建議考慮減碼鎖定獲利，"
        "若有效突破壓力再重新評估。"
    ),
    "red_support": (
        "現價跌破支撐 {support}，風險升高，"
        "請依個人停損計畫評估是否執行停損。"
        "注意：此時停損為保護資金的選項之一，非強制。"
    ),
    "red_stoploss": (
        "現價已低於建議停損區，"
        "建議評估是否執行停損以控制損失。"
        "所有分析僅供參考，最終決策請依個人判斷。"
    ),
}


def _get_reason(
    signal_color: str,
    has_holding: bool,
    current_price: float,
    nearest_support: float | None,
    nearest_resist: float | None
) -> str:
    price = current_price
    support = nearest_support or "—"
    resist  = nearest_resist  or "—"

    if signal_color == "red":
        if nearest_support and current_price > nearest_support * 0.9:
            key = "red_support"
        else:
            key = "red_stoploss"
    elif signal_color == "orange":
        if nearest_resist and current_price >= nearest_resist:
            key = "orange_in"
        else:
            key = "orange_near"
    elif signal_color == "green":
        key = "green_hold" if has_holding else "green_no_hold"
    else:
        key = "yellow_hold" if has_holding else "yellow_no_hold"

    return REASON_TEMPLATES[key].format(
        price=price, support=support, resist=resist
    )


def _get_main_action(
    signal_color: str,
    has_holding: bool,
    signal_desc: str
) -> str:
    mapping = {
        ("red",    True):  "考慮出場",
        ("red",    False): "暫勿買進",
        ("orange", True):  "考慮減碼",
        ("orange", False): "暫勿買進",
        ("yellow", True):  "續抱",
        ("yellow", False): "觀察等待",
        ("green",  True):  "可考慮加碼",
        ("green",  False): "可考慮布局",
    }
    return mapping.get((signal_color, has_holding), "續抱觀察")


def generate_decision_card(
    code: str,
    name: str,
    current_price: float,
    sr_result: SupportResistanceResult,
    signal: SignalResult,
    risk: RiskResult,
    cost: float | None = None,
    shares: int | None = None,
    custom_trim_rules: dict | None = None,
    trim_basis: str = "shares"
) -> DecisionCard:
    """
    生成完整懶人決策卡
    """
    has_holding = bool(cost and shares and shares > 0)

    s_levels = sr_result.support_levels
    r_levels = sr_result.resistance_levels

    nearest_support = s_levels[0].range_high if s_levels else None
    nearest_resist  = r_levels[0].range_low  if r_levels else None
    strong_support  = s_levels[-1].range_low if s_levels else None
    far_resist      = r_levels[-1].range_low if len(r_levels) > 1 else nearest_resist

    # ── 四條觸發條件 ──────────────────────────────────────────
    triggers: list[TriggerAction] = []

    if nearest_support:
        triggers.append(TriggerAction(
            condition=f"{nearest_support} 以下",
            action="觀察，注意支撐是否守住"
        ))

    if nearest_resist:
        triggers.append(TriggerAction(
            condition=f"{nearest_resist} 附近",
            action="接近壓力，考慮減碼"
        ))

    if far_resist and far_resist != nearest_resist:
        triggers.append(TriggerAction(
            condition=f"{far_resist} 以上",
            action="考慮大幅減碼或出場"
        ))

    if strong_support:
        triggers.append(TriggerAction(
            condition=f"跌破 {strong_support}",
            action="停損警示，請評估出場"
        ))
    elif sr_result.stop_loss:
        triggers.append(TriggerAction(
            condition=f"跌破 {sr_result.stop_loss}",
            action="停損警示，請評估出場"
        ))

    # ── 主建議 ────────────────────────────────────────────────
    main_action = _get_main_action(signal.color, has_holding, signal.desc)

    # ── 原因文字 ──────────────────────────────────────────────
    reason = _get_reason(
        signal.color, has_holding,
        current_price, nearest_support, nearest_resist
    )

    # ── 減碼試算（橘/紅燈 + 有持股才附帶）────────────────────
    trim_suggestion = None
    if has_holding and signal.color in ("orange", "red"):
        trim_suggestion = get_trim_suggestion(
            signal_color=signal.color,
            shares=shares,
            current_price=current_price,
            resistance_levels=r_levels,
            custom_rules=custom_trim_rules,
            basis=trim_basis
        )

    # ── 解套模式（有持股 + 虧損中才附帶）────────────────────
    unstuck = None
    if has_holding and cost and current_price < cost:
        unstuck = get_unstuck_evaluation(shares, cost, current_price)

    return DecisionCard(
        stock=code,
        name=name,
        price=current_price,
        signal=signal,
        risk=risk,
        main_action=main_action,
        support_levels=s_levels,
        resistance_levels=r_levels,
        stop_loss=sr_result.stop_loss,
        triggers=triggers,
        reason=reason,
        trim_suggestion=trim_suggestion,
        unstuck_evaluation=unstuck
    )

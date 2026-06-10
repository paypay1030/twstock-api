"""
分析結果 Pydantic 資料模型
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal


# ── 支撐壓力 ──────────────────────────────────────────────────

class SRLevel(BaseModel):
    """單一支撐或壓力位"""
    rank: int = Field(..., description="第幾支撐/壓力，1 最近")
    range_low: float
    range_high: float
    label: str                          # "第一支撐" / "強壓力" 等
    strength: Literal["strong", "normal"]
    score: float = Field(..., ge=0, le=100)
    sources: list[str]                  # 來源，如 ["volume_profile","ma60"]


class SupportResistanceResult(BaseModel):
    support_levels: list[SRLevel]       # 至多 2 個，按距現價由近到遠
    resistance_levels: list[SRLevel]
    stop_loss: float                    # 建議停損價位


# ── 燈號 ──────────────────────────────────────────────────────

class SignalResult(BaseModel):
    color: Literal["green", "yellow", "orange", "red"]
    emoji: str
    label: str
    desc: str


# ── 風險等級 ──────────────────────────────────────────────────

class RiskResult(BaseModel):
    level: Literal["low", "medium", "high"]
    label: str                          # "低" / "中" / "高"
    score: float                        # 0~100
    cost_dist_score: float              # 成本距離分項分
    support_dist_score: float           # 支撐距離分項分
    atr_score: float                    # ATR 分項分


# ── 決策卡 ──────────────────────────────────────────────────

class TriggerAction(BaseModel):
    condition: str                      # "55 以下"
    action: str                         # "觀察，注意支撐"


class TrimSuggestion(BaseModel):
    """減碼試算（當建議減碼時附帶）"""
    trigger: str                        # 觸發條件說明
    pct: float                          # 建議減碼 %
    sell_shares: int
    sell_lots: int
    remain_shares: int
    recover_amount: float
    remain_value: float


class UnstuckEvaluation(BaseModel):
    """解套模式（成本 > 現價時啟動）"""
    cost: float
    current_price: float
    unrealized_loss: float
    unrealized_loss_pct: float
    breakeven_price: float              # 解套價（= 成本）
    stage1_reduce: TrimSuggestion       # 第一段減碼
    stage2_reduce: TrimSuggestion       # 第二段減碼
    evaluation: str                     # 文字說明


class DecisionCard(BaseModel):
    """懶人決策卡完整輸出"""
    stock: str
    name: str
    price: float
    signal: SignalResult
    risk: RiskResult
    main_action: str
    support_levels: list[SRLevel]
    resistance_levels: list[SRLevel]
    stop_loss: float
    triggers: list[TriggerAction]
    reason: str
    trim_suggestion: Optional[TrimSuggestion] = None
    unstuck_evaluation: Optional[UnstuckEvaluation] = None


# ── 完整分析回應 ─────────────────────────────────────────────

class FullAnalysisResponse(BaseModel):
    basic: dict                         # StockBasicInfo
    sr_result: SupportResistanceResult
    decision_card: DecisionCard
    buy_zone: list[float]               # [低, 高]
    sell_zone: list[float]
    stop_loss_zone: list[float]

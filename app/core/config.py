"""
核心設定模組
所有可調整參數集中於此，避免寫死於各 service
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 應用基本設定
    app_name: str = "我的持股管家 API"
    app_env: str = "development"
    app_port: int = 8000
    allowed_origins: list[str] = ["http://localhost:3000"]

    # ── Volume Profile ──────────────────────────────────────
    # 價格分桶數量，可改 30 / 60 / 100
    volume_profile_buckets: int = 60
    # 一般密集區門檻（佔總量比例）
    vp_threshold_normal: float = 0.15
    # 強密集區門檻
    vp_threshold_strong: float = 0.30

    # ── 支撐壓力權重 ─────────────────────────────────────────
    weight_volume_profile: float = 0.40
    weight_historical_hl: float = 0.30
    weight_ma60: float = 0.15
    weight_ma240: float = 0.10
    weight_ma20: float = 0.05

    # 均線納入計算的距離門檻（現價 ±N%）
    ma_proximity_pct: float = 0.03

    # 支撐壓力強度分級
    sr_score_strong: float = 60.0
    sr_score_normal: float = 35.0

    # ── 燈號閾值 ─────────────────────────────────────────────
    signal_resist_near: float = 0.03   # 距壓力 ≤3% → 橘燈
    signal_resist_mid: float = 0.06    # 距壓力 3~6% → 黃燈
    signal_support_near: float = 0.03  # 距支撐 ≤3% → 綠燈

    # ── 風險等級三因子權重 ────────────────────────────────────
    risk_weight_cost_dist: float = 0.40
    risk_weight_support_dist: float = 0.35
    risk_weight_atr: float = 0.25

    # ATR 高波動門檻
    atr_high_threshold: float = 0.04
    atr_low_threshold: float = 0.025

    # ── 預設減碼規則（可於設定頁覆寫）───────────────────────
    trim_rule_near_resist: float = 0.20    # 接近壓力區 → 減20%
    trim_rule_in_resist: float = 0.30      # 進入壓力區 → 減30%
    trim_rule_fail_breakout: float = 0.50  # 突破失敗   → 減50%
    trim_rule_break_support: float = 1.00  # 跌破支撐   → 全出

    # ── 快取設定（秒）────────────────────────────────────────
    cache_ttl_price: int = 300     # 現價快取 5 分鐘
    cache_ttl_history: int = 3600  # 歷史資料快取 1 小時

    # ── 歷史資料設定 ─────────────────────────────────────────
    history_years: int = 3   # 取近幾年資料

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

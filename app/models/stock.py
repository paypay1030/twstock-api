"""
股票相關 Pydantic 資料模型
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class StockBasicInfo(BaseModel):
    """股票基本資訊"""
    symbol: str = Field(..., description="股票代號，如 6770.TW")
    code: str = Field(..., description="純代號，如 6770")
    name: str = Field(..., description="股票名稱")
    current_price: float
    change: float = Field(..., description="今日漲跌金額")
    change_pct: float = Field(..., description="今日漲跌幅 %")
    volume: int = Field(..., description="今日成交量（張）")
    week52_high: float
    week52_low: float
    market_cap: Optional[float] = None


class KLineData(BaseModel):
    """單根 K 棒資料"""
    date: date
    open: float
    high: float
    close: float
    low: float
    volume: int


class StockHistoryResponse(BaseModel):
    """歷史 K 線回應"""
    code: str
    name: str
    klines: list[KLineData]
    ma20: list[Optional[float]]
    ma60: list[Optional[float]]
    ma120: list[Optional[float]]
    ma240: list[Optional[float]]


class StockSearchResult(BaseModel):
    """股票搜尋結果"""
    code: str
    name: str
    market: str = Field(..., description="上市 / 上櫃")

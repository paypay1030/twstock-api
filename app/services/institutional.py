"""
法人資料服務 — 三大法人每日買賣超

目標資料：
  外資、投信、自營商 近五個交易日每日買賣超張數
  來源：TWSE T86（上市）/ TPEX OpenAPI（上櫃）

目前狀態：
  ⚠️  Railway 網路環境無法存取 TWSE / TPEX，暫不取得每日三大法人資料。
  ⚠️  不可使用 yfinance 機構持股資料（institutional_holders / major_holders）
       替代每日三大法人買賣超，兩者是完全不同的資料，不得混用。
  ⚠️  待 Railway 開放 www.twse.com.tw / www.tpex.org.tw 後，
       只需替換 _fetch_twse() / _fetch_tpex() 的實作，
       上層 calculate_institutional() 及前端 API contract 不需修改。

未來串接計畫：
  TWSE 上市：GET https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=YYYYMMDD&selectType=ALL
    → 每次只回傳單日，需對最近 5 個交易日各打一次
    → 欄位：外陸資買進股數、外陸資賣出股數（單位：股，÷1000=張）

  TPEX 上櫃：GET https://www.tpex.org.tw/openapi/v1/tpex_institutional_investors_trading_summary
    → 欄位與單位需以官方文件為準，不得自行假設
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def calculate_institutional(code: str) -> dict:
    """
    取得三大法人近五個交易日買賣超資料。

    目前因網路環境限制，回傳 dataSource='unavailable'。
    API contract 維持不變，前端依 dataSource 判斷是否有真實資料。

    未來串接：只需實作 _fetch_twse() / _fetch_tpex() 並在此處呼叫，
    回傳格式與前端 UI 均不需修改。
    """
    logger.info(f"[institutional] START code={code} → unavailable (TWSE/TPEX network blocked)")

    return {
        "foreign":    [],   # 每日資料列表，格式：[{date, buy, sell, net}, ...]
        "investment": [],
        "dealer":     [],
        "summary": {
            "foreignCumulative":    None,  # 五日累計張數（None = 無資料）
            "investmentCumulative": None,
            "dealerCumulative":     None,
            "foreignTrend":     "unavailable",   # buy | sell | neutral | unavailable
            "investmentTrend":  "unavailable",
            "dealerTrend":      "unavailable",
        },
        "plainTalk":  "目前無法取得三大法人買賣超資料，待後端開放 TWSE/TPEX 連線後將自動更新。",
        "dataSource": "unavailable",    # unavailable | TWSE T86 | TPEX OpenAPI
        "updatedAt":  datetime.now(timezone.utc).isoformat(),
    }


# ── 未來實作預留骨架（目前不呼叫）────────────────────────────

def _fetch_twse(code: str, date_str: str) -> dict | None:
    """
    取得指定日期 TWSE T86 中某股票的三大法人買賣超。

    ⚠️ 待 Railway 開放 www.twse.com.tw 後實作。
    ⚠️ T86 每次只回傳單日資料，需對 5 個交易日分別呼叫。
    ⚠️ 欄位 '外陸資買進股數' 單位為股，÷ 1000 = 張。

    Args:
        code:     股票代號（如 '2330'）
        date_str: 日期字串（格式 'YYYYMMDD'，如 '20241105'）
    Returns:
        {'date': str, 'foreign_net': float, 'invest_net': float, 'dealer_net': float}
        或 None（若該日無資料）
    """
    raise NotImplementedError("待 Railway 開放 www.twse.com.tw 後實作")


def _fetch_tpex(code: str, date_str: str) -> dict | None:
    """
    取得指定日期 TPEX 中某股票的三大法人買賣超。

    ⚠️ 待 Railway 開放 www.tpex.org.tw 後實作。
    ⚠️ 欄位名稱與單位需以官方文件確認，不得自行假設。

    Args:
        code:     股票代號（如 '6770'）
        date_str: 日期字串
    Returns:
        {'date': str, 'foreign_net': float, 'invest_net': float, 'dealer_net': float}
        或 None
    """
    raise NotImplementedError("待 Railway 開放 www.tpex.org.tw 後實作")


def _last_n_trading_dates(n: int = 5) -> list[str]:
    """
    產生最近 n 個交易日的日期字串（YYYYMMDD）。
    ⚠️ 此為輔助函數，待上方 _fetch_twse / _fetch_tpex 實作後使用。
    注意：台股交易日需排除週末與國定假日，目前僅排除週末。
    正式實作應串接台股交易日曆 API 或維護假日清單。
    """
    from datetime import timedelta
    dates = []
    d = datetime.now(timezone.utc)
    while len(dates) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:   # 0=Mon, 4=Fri
            dates.append(d.strftime("%Y%m%d"))
    return dates

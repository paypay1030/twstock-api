"""
三大法人資料服務

資料來源：
  上市（TWSE）：https://www.twse.com.tw/rwd/zh/fund/T86
    → 每日全市場三大法人，date=YYYYMMDD 取單日，需逐日呼叫 5 次
    → 欄位單位：股數，÷1000 = 張
    → 欄位索引（共 19 欄）：
        [0]  證券代號
        [1]  證券名稱
        [2]  外陸資買進股數(不含外資自營商)  ← 外資主力
        [3]  外陸資賣出股數(不含外資自營商)
        [4]  外陸資買賣超股數(不含外資自營商)
        [5]  外資自營商買進股數
        [6]  外資自營商賣出股數
        [7]  外資自營商買賣超股數
        [8]  投信買進股數
        [9]  投信賣出股數
        [10] 投信買賣超股數
        [11] 自營商買賣超股數（合計）
        [12] 自營商買進股數(自行買賣)
        [13] 自營商賣出股數(自行買賣)
        [14] 自營商買賣超股數(自行買賣)
        [15] 自營商買進股數(避險)
        [16] 自營商賣出股數(避險)
        [17] 自營商買賣超股數(避險)
        [18] 三大法人買賣超股數

  上櫃（TPEX）：https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php
    → 回傳 {"tables": [{"fields": [...], "data": [...]},...]}
    → 欄位以 fields 陣列動態確認，不硬編索引
    → 單位：千股（= 張），不需再除以 1000

⚠️ 不得使用 yfinance institutional_holders / major_holders 替代每日買賣超
"""

import logging
import math
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ── 快取：法人資料更新頻率低，TTL 20 分鐘，最多 200 支股票 ──
_inst_cache: TTLCache = TTLCache(maxsize=200, ttl=1200)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; twstock-api/1.0)",
    "Accept":     "application/json, */*",
}


# ════════════════════════════════════════════════════════════
# 工具函數
# ════════════════════════════════════════════════════════════

def _parse_num(s: str) -> Optional[float]:
    """將 TWSE/TPEX 數字字串轉為 float，失敗回傳 None。"""
    if s is None:
        return None
    cleaned = str(s).replace(",", "").replace(" ", "").strip()
    if cleaned in ("", "--", "-", "－"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _shares_to_lots(shares: Optional[float]) -> Optional[int]:
    """股數 ÷ 1000 → 張（TWSE 用）。"""
    if shares is None:
        return None
    return round(shares / 1000)


def _sanitize(obj):
    """遞迴清理 NaN / Infinity → None。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _last_n_weekdays(n: int = 5) -> list[str]:
    """
    產生最近 n 個工作日（週一~週五）的 YYYYMMDD 字串，由新到舊。
    不含今日（盤後資料通常當日收盤後才出）。
    """
    result = []
    d = datetime.now(timezone.utc)
    while len(result) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            result.append(d.strftime("%Y%m%d"))
    return result


def _trend(days: list[dict], key: str) -> str:
    """根據近 5 日 net 判斷趨勢。"""
    nets = [d.get(key) for d in days if d.get(key) is not None]
    if not nets:
        return "neutral"
    pos = sum(1 for v in nets if v > 0)
    neg = sum(1 for v in nets if v < 0)
    if pos >= 4:
        return "buy"
    if neg >= 4:
        return "sell"
    return "neutral"


def _consecutive(days: list[dict], key: str) -> int:
    """
    計算連續買超（正）或賣超（負）天數。
    正數 = 連續買超，負數 = 連續賣超，0 = 無連續。
    days 需由新到舊排列。
    """
    if not days:
        return 0
    first = days[0].get(key)
    if first is None:
        return 0
    direction = 1 if first > 0 else -1
    count = 0
    for d in days:
        v = d.get(key)
        if v is None:
            break
        if (direction == 1 and v > 0) or (direction == -1 and v < 0):
            count += 1
        else:
            break
    return count * direction


def _cumulative(days: list[dict], key: str) -> Optional[int]:
    nets = [d[key] for d in days if d.get(key) is not None]
    if not nets:
        return None
    return round(sum(nets))


# ════════════════════════════════════════════════════════════
# TWSE 上市
# ════════════════════════════════════════════════════════════

async def _fetch_twse_day(client: httpx.AsyncClient, code: str, date: str) -> Optional[dict]:
    """
    取得 TWSE T86 單日指定股票的三大法人資料。
    date: YYYYMMDD
    回傳 None 代表該日無資料（假日或盤後尚未公布）。
    """
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date}&selectType=ALL"
    try:
        resp = await client.get(url, headers={**HEADERS, "Referer": "https://www.twse.com.tw/"})
        j = resp.json()
    except Exception as e:
        logger.warning(f"[twse] {code} {date} fetch error: {e}")
        return None

    if j.get("stat") != "OK":
        logger.debug(f"[twse] {code} {date} stat={j.get('stat')}")
        return None

    fields = j.get("fields", [])
    data   = j.get("data", [])

    # 確認欄位數量符合預期（19 欄）
    if len(fields) != 19:
        logger.warning(f"[twse] unexpected fields count={len(fields)}, fields={fields}")
        return None

    # 找目標股票
    row = next((r for r in data if r and str(r[0]).strip() == code), None)
    if row is None:
        return None

    def col(i: int) -> Optional[float]:
        return _parse_num(row[i]) if i < len(row) else None

    # ── 欄位對應（已由 Render debug 實測確認，2026-08-07 T86 共 19 欄）──
    # col(2)  外陸資買進股數(不含外資自營商)  ← 外資買進主力（股數）
    # col(3)  外陸資賣出股數(不含外資自營商)
    # col(4)  外陸資買賣超股數(不含外資自營商) ← 外資 net，業界標準（不含外資自營商）
    # col(8)  投信買進股數
    # col(9)  投信賣出股數
    # col(10) 投信買賣超股數
    # col(11) 自營商買賣超股數（合計）← 自行+避險合計
    # col(12) 自營商買進股數(自行買賣)
    # col(13) 自營商賣出股數(自行買賣)
    # col(15) 自營商買進股數(避險)
    # col(16) 自營商賣出股數(避險)
    # col(18) 三大法人買賣超股數
    #
    # foreign_buy/sell 只用 col(2)(3)，與 foreign_net col(4) 保持一致
    # （不混入外資自營商，避免 buy-sell ≠ net 的不一致）

    foreign_net  = _shares_to_lots(col(4))
    invest_net   = _shares_to_lots(col(10))
    dealer_net   = _shares_to_lots(col(11))
    total_net    = _shares_to_lots(col(18))

    # dealer buy/sell = 自行買賣 + 避險
    def add_share_cols(a: int, b: int) -> Optional[float]:
        va, vb = col(a), col(b)
        if va is None and vb is None:
            return None
        return (va or 0.0) + (vb or 0.0)

    return {
        "date":         j.get("date", date),
        "date_key":     date,
        "foreign_buy":  _shares_to_lots(col(2)),
        "foreign_sell": _shares_to_lots(col(3)),
        "foreign_net":  foreign_net,
        "invest_buy":   _shares_to_lots(col(8)),
        "invest_sell":  _shares_to_lots(col(9)),
        "invest_net":   invest_net,
        "dealer_buy":   _shares_to_lots(add_share_cols(12, 15)),
        "dealer_sell":  _shares_to_lots(add_share_cols(13, 16)),
        "dealer_net":   dealer_net,
        "total_net":    total_net,
    }


async def _fetch_twse(code: str) -> list[dict]:
    """取得 TWSE 最近 5 個已公布交易日的三大法人資料（由新到舊）。"""
    dates   = _last_n_weekdays(15)   # 多取幾天應對台灣連續假日
    results = []

    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for date in dates:
            if len(results) >= 5:
                break
            row = await _fetch_twse_day(client, code, date)
            if row:
                results.append(row)
            await asyncio.sleep(0.3)   # 避免過快打 TWSE

    return results   # 最多 5 筆，由新到舊


# ════════════════════════════════════════════════════════════
# TPEX 上櫃
# ════════════════════════════════════════════════════════════

async def _fetch_tpex_day(client: httpx.AsyncClient, code: str, date_str: str) -> Optional[dict]:
    """
    取得 TPEX 單日指定股票的三大法人資料。
    date_str: YYYY/MM/DD

    欄位索引（由 Render 實測 2026-08-21 確認，共 24 欄）：
      [0]  代號
      [1]  名稱
      [2]  外資及陸資買進股數     （千股=張）
      [3]  外資及陸資賣出股數
      [4]  外資及陸資買賣超股數   ← 外資主力（業界慣用）
      [5]  外資自營商買進股數
      [6]  外資自營商賣出股數
      [7]  外資自營商買賣超股數
      [8]  外資合計買進股數
      [9]  外資合計賣出股數
      [10] 外資合計買賣超股數     ← 外資+外資自營商合計
      [11] 投信買進股數
      [12] 投信賣出股數
      [13] 投信買賣超股數         ← 投信
      [14] 自營商(自行)買進股數
      [15] 自營商(自行)賣出股數
      [16] 自營商(自行)買賣超股數
      [17] 自營商(避險)買進股數
      [18] 自營商(避險)賣出股數
      [19] 自營商(避險)買賣超股數
      [20] 自營商合計買進股數
      [21] 自營商合計賣出股數
      [22] 自營商合計買賣超股數   ← 自營商（自行+避險合計）
      [23] 三大法人買賣超股數合計

    單位：千股（= 張），直接使用，不需再除以 1000。
    驗算（1565 精華 2026-08-21）：外資1953 + 投信0 + 自營-116 = 1837 ✅
    """
    url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&se=AL&t=D&d={date_str}"
    )
    try:
        resp = await client.get(url, headers={**HEADERS, "Referer": "https://www.tpex.org.tw/"})
        j = resp.json()
    except Exception as e:
        logger.warning(f"[tpex] {code} {date_str} fetch error: {e}")
        return None

    tables = j.get("tables", [])
    if not tables:
        return None

    # 找第一個有 data 的 table
    target_table = next((t for t in tables if t.get("data")), None)
    if not target_table:
        return None

    fields = target_table.get("fields", [])
    data   = target_table["data"]

    # 確認欄位數量（24 欄），避免 TPEX 改版時默默算錯
    if len(fields) != 24:
        logger.warning(f"[tpex] {code} {date_str} unexpected fields count={len(fields)}")
        # 欄位數不符時仍嘗試解析，但記錄警告供排查
        if len(fields) < 24:
            return None

    # 找目標股票（第一欄為代號）
    row = next((r for r in data if r and str(r[0]).strip() == code), None)
    if row is None:
        return None

    def col(i: int) -> Optional[float]:
        """取第 i 欄的數值（千股），回傳 None 表示無資料。"""
        if i >= len(row):
            return None
        return _parse_num(row[i])

    def to_lots(v: Optional[float]) -> Optional[int]:
        """千股直接取整為張。"""
        return round(v) if v is not None else None

    # 使用確認的索引（見上方 docstring）
    foreign_net = to_lots(col(4))    # 外資及陸資買賣超（業界標準）
    invest_net  = to_lots(col(13))   # 投信買賣超
    dealer_net  = to_lots(col(22))   # 自營商合計買賣超
    total_net   = to_lots(col(23))   # 三大法人合計

    date_key = date_str.replace("/", "")

    return {
        "date":         date_str,
        "date_key":     date_key,
        "foreign_buy":  to_lots(col(2)),
        "foreign_sell": to_lots(col(3)),
        "foreign_net":  foreign_net,
        "invest_buy":   to_lots(col(11)),
        "invest_sell":  to_lots(col(12)),
        "invest_net":   invest_net,
        "dealer_buy":   to_lots(col(20)),
        "dealer_sell":  to_lots(col(21)),
        "dealer_net":   dealer_net,
        "total_net":    total_net,
    }


async def _fetch_tpex(code: str) -> list[dict]:
    """取得 TPEX 最近 5 個已公布交易日的三大法人資料（由新到舊）。"""
    results = []
    base = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        d = base
        attempts = 0
        while len(results) < 5 and attempts < 15:
            d -= timedelta(days=1)
            attempts += 1
            if d.weekday() >= 5:
                continue
            date_str = f"{d.year}/{d.month:02d}/{d.day:02d}"
            row = await _fetch_tpex_day(client, code, date_str)
            if row:
                results.append(row)
            await asyncio.sleep(0.3)

    return results


# ════════════════════════════════════════════════════════════
# 上市 / 上櫃 判斷
# ════════════════════════════════════════════════════════════

def _is_tpex(code: str) -> bool:
    """
    判斷股票是否為上櫃（TPEX）。
    優先從 stock_list_cache 查詢，找不到再用代號特徵 fallback。
    """
    try:
        from app.utils.stock_list import stock_list_cache
        entry = stock_list_cache.get_by_code(code)
        if entry is not None:
            market = entry.get("market", "")
            return "上櫃" in market
    except Exception as e:
        logger.debug(f"[_is_tpex] stock_list_cache error: {e}")

    # Fallback：代號特徵（stock_list 找不到時）
    if code.startswith("0"):
        return False   # ETF（0050, 00878 等）→ 上市
    if code.endswith(("R", "T", "U", "B")):
        return False   # 受益憑證 → 上市
    if len(code) == 4 and code[0] in ("4", "5", "7", "8"):
        return True    # 高機率上櫃
    return False       # 預設上市（保守）


# ════════════════════════════════════════════════════════════
# 主函數（router 呼叫此處）
# ════════════════════════════════════════════════════════════

async def calculate_institutional(code: str) -> dict:
    """
    取得三大法人近 5 個交易日買賣超資料。
    上市 → TWSE T86；上櫃 → TPEX 3itrade。
    """
    cache_key = f"inst:{code}"
    if cache_key in _inst_cache:
        logger.debug(f"[institutional] cache hit: {code}")
        return _inst_cache[cache_key]

    logger.info(f"[institutional] START code={code}")

    try:
        use_tpex = _is_tpex(code)
        logger.info(f"[institutional] code={code} use_tpex={use_tpex}")

        if use_tpex:
            days = await _fetch_tpex(code)
            data_source = "TPEX 3itrade"
        else:
            days = await _fetch_twse(code)
            data_source = "TWSE T86"

        if not days:
            logger.warning(f"[institutional] no data for {code}")
            result = _empty_response("no_data")
            result["dataSource"] = data_source
            return result

        # 格式化成 API response 結構
        def fmt_days(net_key: str, buy_key: str = None, sell_key: str = None) -> list[dict]:
            out = []
            for d in days:
                out.append({
                    "date":  d["date"],
                    "buy":   d.get(buy_key) if buy_key else None,
                    "sell":  d.get(sell_key) if sell_key else None,
                    "net":   d.get(net_key),
                })
            return out

        foreign_days    = fmt_days("foreign_net", "foreign_buy", "foreign_sell")
        investment_days = fmt_days("invest_net",  "invest_buy",  "invest_sell")
        dealer_days     = fmt_days("dealer_net",  "dealer_buy",  "dealer_sell")

        f_cum = _cumulative(days, "foreign_net")
        i_cum = _cumulative(days, "invest_net")
        d_cum = _cumulative(days, "dealer_net")
        t_cum = _cumulative(days, "total_net")

        f_con = _consecutive(days, "foreign_net")
        i_con = _consecutive(days, "invest_net")
        d_con = _consecutive(days, "dealer_net")

        f_trend = _trend(days, "foreign_net")
        i_trend = _trend(days, "invest_net")
        d_trend = _trend(days, "dealer_net")

        plain = _generate_plain_talk(
            days, f_trend, i_trend, d_trend,
            f_cum, i_cum, d_cum, f_con, i_con
        )

        result = _sanitize({
            "foreign":    foreign_days,
            "investment": investment_days,
            "dealer":     dealer_days,
            "summary": {
                "foreignCumulative":    f_cum,
                "investmentCumulative": i_cum,
                "dealerCumulative":     d_cum,
                "totalCumulative":      t_cum,
                "foreignTrend":     f_trend,
                "investmentTrend":  i_trend,
                "dealerTrend":      d_trend,
                "foreignConsecutive":    f_con,
                "investmentConsecutive": i_con,
                "dealerConsecutive":     d_con,
            },
            "plainTalk":  plain,
            "dataSource": data_source,
            "tradingDates": [d["date"] for d in days],
            "updatedAt":  datetime.now(timezone.utc).isoformat(),
        })

        _inst_cache[cache_key] = result
        logger.info(f"[institutional] DONE code={code} days={len(days)} source={data_source}")
        return result

    except Exception as e:
        import traceback
        logger.error(f"[institutional] ERROR code={code}: {e}\n{traceback.format_exc()}")
        return _empty_response("error")


def _empty_response(reason: str = "unavailable") -> dict:
    return {
        "foreign":    [],
        "investment": [],
        "dealer":     [],
        "summary": {
            "foreignCumulative":     None,
            "investmentCumulative":  None,
            "dealerCumulative":      None,
            "totalCumulative":       None,
            "foreignTrend":          "unavailable",
            "investmentTrend":       "unavailable",
            "dealerTrend":           "unavailable",
            "foreignConsecutive":    0,
            "investmentConsecutive": 0,
            "dealerConsecutive":     0,
        },
        "plainTalk":    "目前無法取得三大法人資料。",
        "dataSource":   reason,
        "tradingDates": [],
        "updatedAt":    datetime.now(timezone.utc).isoformat(),
    }


def _generate_plain_talk(
    days:    list[dict],
    f_trend: str, i_trend: str, d_trend: str,
    f_cum:   Optional[int], i_cum: Optional[int], d_cum: Optional[int],
    f_con:   int, i_con: int,
) -> str:
    if not days:
        return "目前無法取得三大法人資料。"

    parts = []

    # 外資
    if f_cum is not None:
        direction = "買超" if f_cum > 0 else "賣超"
        if abs(f_con) >= 3:
            parts.append(f"外資已連續{abs(f_con)}天{direction}，五日累計{'+' if f_cum>0 else ''}{f_cum:,}張")
        else:
            parts.append(f"外資五日累計{'+' if f_cum>0 else ''}{f_cum:,}張")

    # 投信
    if i_cum is not None:
        direction = "買超" if i_cum > 0 else "賣超"
        if abs(i_con) >= 2:
            parts.append(f"投信連續{abs(i_con)}天{direction}、累計{'+' if i_cum>0 else ''}{i_cum:,}張")
        else:
            parts.append(f"投信五日累計{'+' if i_cum>0 else ''}{i_cum:,}張")

    # 整體解讀
    if f_trend == "buy" and i_trend == "sell":
        parts.append("外資持續買進但投信調節，籌碼方向分歧，建議觀察後續量能")
    elif f_trend == "buy" and i_trend == "buy":
        parts.append("外資與投信同步買超，籌碼偏多")
    elif f_trend == "sell" and i_trend == "sell":
        parts.append("外資與投信同步賣超，籌碼偏空，留意下行風險")
    elif f_trend == "sell" and i_trend == "buy":
        parts.append("外資賣出但投信承接，方向分歧")
    else:
        parts.append("法人方向中性，觀察為主")

    return "，".join(parts) + "。"

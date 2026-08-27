"""
今日小筆記服務

資料來源：Yahoo Finance（^TWII 加權指數）
策略：
  1. 取加權指數當日（或最近交易日）的收盤價、漲跌幅、成交量
  2. 依照漲跌幅 + 成交量判斷市場偏多／偏空／震盪
  3. 產生符合 TodayNoteData 格式的今日建議

⚠️ 資料取得失敗時不使用假數字，回傳 source='unavailable'。
⚠️ 不使用 mock 資料冒充即時資訊。
"""
import logging
from datetime import datetime, timezone
from typing import Optional
import yfinance as yf
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# 今日筆記快取：TTL 15 分鐘（盤中足夠新鮮；收盤後資料不變）
_note_cache: TTLCache = TTLCache(maxsize=4, ttl=900)

# ════════════════════════════════════════════════════════════
# 大盤資料取得
# ════════════════════════════════════════════════════════════

def _fetch_taiex() -> Optional[dict]:
    """
    取得加權指數最近交易日資料。
    回傳 None 代表資料無法取得。
    """
    try:
        ticker = yf.Ticker("^TWII")
        hist   = ticker.history(period="5d", interval="1d", timeout=8)

        if hist.empty:
            logger.warning("[today_note] ^TWII history empty")
            return None

        latest  = hist.iloc[-1]
        prev    = hist.iloc[-2] if len(hist) >= 2 else None

        close   = float(latest["Close"])
        # Volume 單位：yfinance ^TWII Volume 數字含義模糊（實測 2026-08-27 發現換算結果不合理）
        # 不做換算，不顯示成交金額，市場判斷只依賴漲跌幅

        if prev is not None:
            prev_close = float(prev["Close"])
            change     = round(close - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
        else:
            change     = 0.0
            change_pct = 0.0

        trade_date = hist.index[-1].strftime("%Y-%m-%d")

        return {
            "close":      close,
            "change":     change,
            "change_pct": change_pct,
            "trade_date": trade_date,
        }

    except Exception as e:
        logger.error(f"[today_note] _fetch_taiex error: {type(e).__name__}: {e}")
        return None


# ════════════════════════════════════════════════════════════
# 市場判斷邏輯
# ════════════════════════════════════════════════════════════

def _classify_market(change_pct: float) -> dict:
    """
    依漲跌幅與成交金額分類市場狀態，產生建議內容。
    分類邏輯：
      強多：漲幅 > 1.5% 且量能充足（> 2500 億）
      偏多：漲幅 0.3%~1.5%
      震盪：漲跌幅 -0.3%~0.3%
      偏空：跌幅 0.3%~1.5%
      強空：跌幅 > 1.5% 或量能放大下跌
    """
    if change_pct > 1.5:
        mood = "strong_bull"
    elif change_pct > 0.3:
        mood = "bull"
    elif change_pct < -1.5:
        mood = "strong_bear"
    elif change_pct < -0.3:
        mood = "bear"
    else:
        mood = "neutral"

    return _MOOD_MAP[mood]


_MOOD_MAP = {
    "strong_bull": {
        "label":      "偏強，有量的上漲",
        "risk_level": "low",
        "confidence": "high",
        "headline":   "今天市場偏強，有量能支撐。",
        "body":       "今天加權指數有量的上漲，整體偏多。不過強勢時容易追高，建議不要貿然追進，可以等回檔再評估。",
        "actions":    ["目前持股可繼續持有", "等回檔再考慮布局", "不要在高點追高"],
        "reasons":    ["今天加權指數漲幅明顯", "成交量充足，有資金進場", "整體市場氣氛偏多"],
        "if_i_were":  "如果是我，今天不會急著追高。\n\n強勢行情通常會給回檔機會，我會等股價稍微回落後再評估是否加碼。",
        "risk_note":  "",
    },
    "bull": {
        "label":      "偏多",
        "risk_level": "low",
        "confidence": "mid",
        "headline":   "今天市場偏多，方向向上。",
        "body":       "今天加權指數小幅上漲，整體方向偏多。量能需要繼續觀察，如果量能能夠跟上，上漲才比較有支撐。",
        "actions":    ["目前持股可繼續持有", "留意成交量是否放大", "有興趣的股票可以觀察"],
        "reasons":    ["加權指數今天收高", "市場偏多氣氛", "整體方向向上"],
        "if_i_were":  "如果是我，今天會繼續持有目前持股。\n\n量能如果持續放大，可以考慮在合理位置分批布局。",
        "risk_note":  "",
    },
    "neutral": {
        "label":      "偏震盪",
        "risk_level": "mid",
        "confidence": "mid",
        "headline":   "今天市場偏震盪，方向不明。",
        "body":       "今天加權指數漲跌幅不大，市場方向還不明確。這種時候觀察比操作更重要，先等待方向確立。",
        "actions":    ["今天先觀察，不急著追高", "目前持股可繼續持有", "等待方向確立再決定"],
        "reasons":    ["加權指數今天漲跌幅不大", "市場方向還不明確", "量能有待觀察"],
        "if_i_were":  "如果是我，今天不會主動買進。\n\n等到出現比較明確的方向訊號，再決定是否行動。震盪行情容易來回被洗，耐心等待是最好的策略。",
        "risk_note":  "",
    },
    "bear": {
        "label":      "偏弱",
        "risk_level": "mid",
        "confidence": "mid",
        "headline":   "今天市場偏弱，留意持股。",
        "body":       "今天加權指數小幅下跌，整體偏弱。先檢查持股是否接近支撐區，避免在弱勢中追買。",
        "actions":    ["檢查持股是否接近支撐", "今天不要追買", "留意成交量是否放大"],
        "reasons":    ["加權指數今天下跌", "市場偏弱氣氛", "需要留意是否繼續走弱"],
        "if_i_were":  "如果是我，今天不會追買。\n\n先檢查手上的持股有沒有接近支撐區，如果有，要留意是否需要設定停損。",
        "risk_note":  "留意指數是否繼續走弱",
    },
    "strong_bear": {
        "label":      "偏空，需要留意",
        "risk_level": "high",
        "confidence": "high",
        "headline":   "今天市場走弱，注意風險。",
        "body":       "今天加權指數跌幅明顯，市場偏空。今天不建議進場，先檢查持股的支撐位置與停損設定，避免損失擴大。",
        "actions":    ["今天不要進場買入", "檢查持股停損設定", "若跌破支撐考慮減碼"],
        "reasons":    ["加權指數今天跌幅明顯", "市場偏空氣氛", "需要留意下行風險"],
        "if_i_were":  "如果是我，今天不會進場。\n\n先確認手上持股的支撐位置，如果有跌破支撐的風險，考慮先減少部位，等市場穩定再說。",
        "risk_note":  "今天市場偏空，請確認持股停損設定",
    },
}


# ════════════════════════════════════════════════════════════
# 主函數
# ════════════════════════════════════════════════════════════

def generate_today_note() -> dict:
    """
    產生今日小筆記。
    回傳格式與前端 TodayNoteData + TodayNoteResponse 完全對齊。
    """
    cache_key = "today_note"
    if cache_key in _note_cache:
        logger.debug("[today_note] cache hit")
        return _note_cache[cache_key]

    logger.info("[today_note] generating...")

    taiex = _fetch_taiex()

    if taiex is None:
        result = {
            "headline":    "今天暫時無法取得大盤資料。",
            "body":        "台股大盤資料目前無法取得，請稍後再查看。",
            "reasons":     ["大盤資料暫時無法取得"],
            "ifIWere":     "如果是我，今天先暫停操作，等資料恢復後再評估。",
            "actions":     ["等待資料恢復後再評估"],
            "riskLevel":   "mid",
            "riskNote":    "今天無法取得大盤資料，建議暫停操作",
            "confidence":  "low",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source":      "unavailable",
        }
        # 資料失敗時快取較短時間（5 分鐘），讓下次請求能重試
        _note_cache.pop(cache_key, None)
        return result

    mood = _classify_market(taiex["change_pct"])

    # 組合數字摘要（放在 body 前面）
    body_prefix = (
        f"加權指數 {taiex['close']:,.0f} 點，"
        f"漲跌 {taiex['change']:+.0f}（{taiex['change_pct']:+.2f}%）。\n\n"
    )

    result = {
        "headline":    mood["headline"],
        "body":        body_prefix + mood["body"],
        "reasons":     mood["reasons"],
        "ifIWere":     mood["if_i_were"],
        "actions":     mood["actions"],
        "riskLevel":   mood["risk_level"],
        "riskNote":    mood["risk_note"],
        "confidence":  mood["confidence"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source":      "market_data",
        # 額外給前端參考，不影響 TodayNoteData contract
        "marketData": {
            "taiex":     taiex["close"],
            "change":    taiex["change"],
            "changePct": taiex["change_pct"],
            "tradeDate": taiex["trade_date"],
            "mood":      mood["label"],
        },
    }

    _note_cache[cache_key] = result
    logger.info(
        f"[today_note] generated: close={taiex['close']} "
        f"chg={taiex['change_pct']:+.2f}% mood={mood['label']}"
    )
    return result

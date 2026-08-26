"""
分析 Router

原則：分析結果不受個人持股成本影響。
      支撐壓力、燈號、風險等級純技術分析。
"""
import math
import logging
import traceback
from fastapi import APIRouter, HTTPException
from app.services.stock_fetcher import get_stock_basic, get_stock_history, DataSourceError
from app.services.support_resistance import calculate_sr
from app.services.risk_engine import calculate_signal, calculate_risk
from app.services.decision_card import generate_decision_card
from app.services.indicators import calculate_indicators
from cachetools import TTLCache as _TTLCache

# indicators 快取：TTL 1 小時，最多 200 支
_ind_cache: _TTLCache = _TTLCache(maxsize=200, ttl=3600)

router = APIRouter(prefix="/api/analysis", tags=["分析"])
logger = logging.getLogger(__name__)


def _sanitize(obj):
    """
    遞迴清理 dict / list 中的 NaN、Infinity，
    替換為 None（JSON 序列化為 null），避免 JSON encode 失敗。
    ETF 資料不完整時特別容易出現這類值。
    """
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


@router.post("/{code}")
@router.get("/{code}")
async def analyze(code: str):
    """
    純技術分析，不接受個人成本作為輸入。
    個人持股資訊由前端疊加顯示，不影響分析結果。
    """
    try:
        logger.info(f"[analyze] START code={code}")

        logger.info(f"[analyze] fetching basic info: {code}")
        basic = get_stock_basic(code)
        price = basic["current_price"]
        logger.info(f"[analyze] basic OK: name={basic['name']} price={price}")

        logger.info(f"[analyze] fetching history: {code}")
        df = get_stock_history(code)
        logger.info(f"[analyze] history OK: rows={len(df)} cols={list(df.columns)}")

        # 記錄 DataFrame 狀態，幫助診斷 ETF 資料問題
        import numpy as np
        nan_counts = df.isna().sum().to_dict()
        inf_counts = {c: int(np.isinf(df[c]).sum()) for c in df.select_dtypes(include=[np.number]).columns}
        if any(v > 0 for v in nan_counts.values()):
            logger.warning(f"[analyze] NaN counts in df: {nan_counts}")
        if any(v > 0 for v in inf_counts.values()):
            logger.warning(f"[analyze] inf counts in df: {inf_counts}")

        logger.info(f"[analyze] calculating SR: {code}")
        sr_result = calculate_sr(df, price)
        logger.info(f"[analyze] SR OK: supports={len(sr_result.support_levels)} resists={len(sr_result.resistance_levels)}")

        logger.info(f"[analyze] calculating signal: {code}")
        signal = calculate_signal(
            price,
            sr_result.support_levels,
            sr_result.resistance_levels,
            sr_result.stop_loss
        )
        logger.info(f"[analyze] signal OK: {signal.color} {signal.label}")

        logger.info(f"[analyze] calculating risk: {code}")
        risk = calculate_risk(price, None, sr_result.support_levels, df)
        logger.info(f"[analyze] risk OK: {risk.level} score={risk.score}")

        logger.info(f"[analyze] generating decision card: {code}")
        card = generate_decision_card(
            code=code,
            name=basic["name"],
            current_price=price,
            sr_result=sr_result,
            signal=signal,
            risk=risk,
        )
        logger.info(f"[analyze] card OK: action={card.main_action}")

        raw = {
            "basic":          basic,
            "sr_result":      sr_result.model_dump(),
            "decision_card":  card.model_dump(),
            "buy_zone":       _buy_zone(sr_result, price),
            "sell_zone":      _sell_zone(sr_result, price),
            "stop_loss_zone": [sr_result.stop_loss, round(sr_result.stop_loss * 0.98, 2)],
            "disclaimer":     "所有分析均為機率與風險評估，不保證未來股價走勢。"
        }
        # 最終防線：清理所有殘餘 NaN / Infinity，避免 JSON 序列化失敗
        sanitized = _sanitize(raw)
        logger.info(f"[analyze] DONE code={code}")
        return sanitized

    except DataSourceError as e:
        logger.error(f"[analyze] DataSourceError code={code}: {e}")
        raise HTTPException(503, detail=str(e))
    except ValueError as e:
        logger.error(f"[analyze] ValueError code={code}: {e}")
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        # 完整 traceback 記錄到 Railway log
        logger.error(
            f"[analyze] UNEXPECTED ERROR code={code}: {type(e).__name__}: {e}\n"
            + traceback.format_exc()
        )
        raise HTTPException(500, detail=f"分析失敗：{type(e).__name__}: {e}")


def _buy_zone(sr, price):
    return [sr.support_levels[0].range_low, sr.support_levels[0].range_high] \
        if sr.support_levels else [round(price * 0.95, 2), round(price * 0.97, 2)]


def _sell_zone(sr, price):
    return [sr.resistance_levels[0].range_low, sr.resistance_levels[0].range_high] \
        if sr.resistance_levels else [round(price * 1.05, 2), round(price * 1.08, 2)]


# ════════════════════════════════════════════════════════════
# GET /api/analysis/{code}/indicators
# 技術指標快照（MA / RSI / MACD / KD / Bollinger Bands）
# ════════════════════════════════════════════════════════════

@router.get("/{code}/indicators")
async def get_indicators(code: str):
    """
    取得股票技術指標快照。
    TTL 1 小時快取，避免重複計算。
    """
    # 快取命中
    if code in _ind_cache:
        logger.debug(f"[indicators] cache hit: {code}")
        return _ind_cache[code]

    last_err = None
    for attempt in range(2):   # 最多 retry 1 次
        try:
            logger.info(f"[indicators] START code={code} attempt={attempt+1}")
            df = get_stock_history(code)
            result = calculate_indicators(df)
            result = _sanitize(result)
            _ind_cache[code] = result
            logger.info(f"[indicators] DONE code={code} trend={result.get('trend')}")
            return result
        except DataSourceError as e:
            last_err = e
            logger.warning(f"[indicators] DataSourceError attempt={attempt+1}: {e}")
            if attempt == 0:
                await __import__('asyncio').sleep(1)
        except Exception as e:
            last_err = e
            logger.error(f"[indicators] ERROR attempt={attempt+1}: {type(e).__name__}: {e}")
            if attempt == 0:
                await __import__('asyncio').sleep(1)

    # retry 後仍失敗
    if isinstance(last_err, DataSourceError):
        raise HTTPException(503, detail=str(last_err))
    raise HTTPException(500, detail=f"技術指標計算失敗，請稍後再試")


# ════════════════════════════════════════════════════════════
# GET /api/analysis/{code}/institutional
# ════════════════════════════════════════════════════════════
from app.services.institutional import calculate_institutional, _inst_cache

@router.get("/{code}/institutional")
async def get_institutional(code: str, force: bool = False):
    """
    三大法人近五個交易日買賣超資料（外資、投信、自營商）。
    上市 → TWSE T86；上櫃 → TPEX 3itrade。
    force=true 可強制清除快取重新取得。
    """
    if force:
        cache_key = f"inst:{code}"
        if cache_key in _inst_cache:
            del _inst_cache[cache_key]
            logger.info(f"[institutional] cache cleared: {code}")
    try:
        logger.info(f"[institutional] START code={code} force={force}")
        result = await calculate_institutional(code)
        logger.info(f"[institutional] DONE code={code}")
        return result
    except Exception as e:
        logger.error(
            f"[institutional] ERROR code={code}: {type(e).__name__}: {e}\n"
            + __import__("traceback").format_exc()
        )
        raise HTTPException(500, detail=f"法人資料取得失敗：{type(e).__name__}: {e}")


# ════════════════════════════════════════════════════════════
# 連線健康檢查（用於監控 TWSE 連線狀況）
# production 環境需傳入 key=<DEBUG_KEY> 才能呼叫
# ════════════════════════════════════════════════════════════
import os as _os

@router.get("/debug/twse-connection")
async def check_twse_connection(key: str = ""):
    """
    確認後端可連線 TWSE T86。
    production 環境需傳入 ?key=<DEBUG_KEY> 環境變數值。
    """
    debug_key = _os.environ.get("DEBUG_KEY", "")
    app_env   = _os.environ.get("APP_ENV", "development")
    if app_env == "production" and (not debug_key or key != debug_key):
        raise HTTPException(403, detail="需要提供正確的 debug key")

    import httpx as _httpx
    url = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALL"
    try:
        async with _httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; twstock-api/1.0)",
                "Referer":    "https://www.twse.com.tw/",
            })
        j = resp.json()
        return {
            "ok":        resp.status_code == 200,
            "status":    resp.status_code,
            "twse_stat": j.get("stat"),
            "twse_date": j.get("date"),
            "row_count": len(j.get("data", [])),
        }
    except _httpx.TimeoutException:
        return {"ok": False, "error_type": "TimeoutException"}
    except _httpx.ConnectError as e:
        return {"ok": False, "error_type": "ConnectError", "error": str(e)[:120]}
    except Exception as e:
        return {"ok": False, "error_type": type(e).__name__, "error": str(e)[:120]}

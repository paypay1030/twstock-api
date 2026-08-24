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

    回傳最新一根 K 線對應的技術指標數值，
    計算基礎為近 756 個交易日（約 3 年）歷史 K 線資料。

    回傳格式與前端 TechIndicators 介面完全對齊。
    """
    try:
        logger.info(f"[indicators] START code={code}")

        df = get_stock_history(code)
        logger.info(f"[indicators] history OK: rows={len(df)}")

        result = calculate_indicators(df)
        result = _sanitize(result)

        logger.info(f"[indicators] DONE code={code} trend={result.get('trend')}")
        return result

    except DataSourceError as e:
        logger.error(f"[indicators] DataSourceError code={code}: {e}")
        raise HTTPException(503, detail=str(e))
    except Exception as e:
        logger.error(
            f"[indicators] ERROR code={code}: {type(e).__name__}: {e}\n"
            + traceback.format_exc()
        )
        raise HTTPException(500, detail=f"指標計算失敗：{type(e).__name__}: {e}")


# ════════════════════════════════════════════════════════════
# GET /api/analysis/{code}/institutional
# ════════════════════════════════════════════════════════════
from app.services.institutional import calculate_institutional

@router.get("/{code}/institutional")
async def get_institutional(code: str):
    """
    三大法人近五個交易日買賣超資料（外資、投信、自營商）。
    上市 → TWSE T86；上櫃 → TPEX 3itrade。
    Render 生產環境已確認可連線 TWSE/TPEX（2026-08-13 實測）。
    """
    try:
        logger.info(f"[institutional] START code={code}")
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
# DEBUG ONLY — Railway TWSE 連線實測
# 僅供確認 Railway 網路環境是否可直接連 TWSE，不用於正式功能
# 部署確認後可移除
# ════════════════════════════════════════════════════════════
import httpx as _httpx

@router.get("/debug/twse-connection")
async def debug_twse_connection():
    """
    診斷 Railway 生產環境是否可直接連線 TWSE T86。
    只回傳連線結果，不回傳完整 TWSE response body。
    """
    url = "https://www.twse.com.tw/fund/T86?response=json&date=20260807&selectType=ALL"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; twstock-debug/1.0)",
        "Accept": "application/json, */*",
    }

    try:
        async with _httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

        content_type = resp.headers.get("content-type", "unknown")
        body_len = len(resp.content)

        # 嘗試解析 JSON 確認資料結構（不回傳完整 body）
        try:
            j = resp.json()
            data_stat  = j.get("stat", "N/A")
            data_date  = j.get("date", "N/A")
            row_count  = len(j.get("data", []))
        except Exception:
            data_stat = "parse_error"
            data_date = "N/A"
            row_count = 0

        return {
            "ok":              resp.status_code == 200,
            "status":          resp.status_code,
            "content_type":    content_type,
            "response_length": body_len,
            "twse_stat":       data_stat,   # "OK" or error string from TWSE
            "twse_date":       data_date,   # date field returned by TWSE
            "row_count":       row_count,   # number of stocks in response
            "note":            "debug endpoint — do not use in production logic",
        }

    except _httpx.TimeoutException as e:
        return {"ok": False, "error_type": "TimeoutException",    "error": str(e)}
    except _httpx.ConnectError as e:
        return {"ok": False, "error_type": "ConnectError",        "error": str(e)}
    except _httpx.TooManyRedirects as e:
        return {"ok": False, "error_type": "TooManyRedirects",    "error": str(e)}
    except _httpx.HTTPStatusError as e:
        return {"ok": False, "error_type": "HTTPStatusError",
                "status": e.response.status_code, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error_type": type(e).__name__,      "error": str(e)}


@router.get("/debug/tpex-connection")
async def debug_tpex_connection():
    """
    回傳 TPEX 1565 的原始 tables[0].fields 與 row，
    供確認欄位名稱與對應值。Debug only。
    """
    import httpx as _httpx
    from datetime import datetime, timedelta
    d = datetime.now()
    for _ in range(7):
        d -= timedelta(days=1)
        if d.weekday() < 5:
            break
    date_str = f"{d.year}/{d.month:02d}/{d.day:02d}"
    url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&se=AL&t=D&d={date_str}"
    )
    try:
        async with _httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; twstock-debug/1.0)",
                "Accept": "application/json, */*",
                "Referer": "https://www.tpex.org.tw/",
            })
        j = resp.json()
        tables = j.get("tables", [])
        if not tables:
            return {"error": "no tables", "keys": list(j.keys()), "date": date_str}
        t0 = tables[0]
        fields = t0.get("fields", [])
        data   = t0.get("data",   [])
        # 找 1565
        row_1565 = next((r for r in data if r and str(r[0]).strip() == "1565"), None)
        # 回傳欄位對照表
        field_map = None
        if row_1565:
            field_map = {f"[{i}] {fields[i]}": row_1565[i] for i in range(min(len(fields), len(row_1565)))}
        return {
            "date":       date_str,
            "status":     resp.status_code,
            "table_count": len(tables),
            "fields":     fields,
            "row_1565":   row_1565,
            "field_map":  field_map,
        }
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@router.get("/debug/twse-fields")
async def debug_twse_fields():
    """
    確認 TWSE T86 與 TPEX OpenAPI 的實際欄位名稱與單位。
    僅供 Phase 14 開發確認，確認後移除。
    """
    import httpx as _hx
    results = {}

    # ── TWSE T86 fields 確認 ──
    try:
        async with _hx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(
                "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=20260807&selectType=ALL",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.twse.com.tw/"}
            )
        j = r.json()
        fields = j.get("fields", [])
        # 找 2330 的資料行
        row_2330 = next((row for row in j.get("data", []) if row and row[0] == "2330"), None)
        results["twse"] = {
            "stat": j.get("stat"),
            "date": j.get("date"),
            "fields": fields,
            "fields_count": len(fields),
            "sample_2330_raw": row_2330,  # 原始字串，確認格式
        }
    except Exception as e:
        results["twse"] = {"error": str(e)}

    # ── TPEX OpenAPI fields 確認 ──
    try:
        async with _hx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(
                "https://www.tpex.org.tw/openapi/v1/tpex_institutional_investors_trading_summary",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            )
        data = r.json()
        # 取前 3 筆確認格式
        sample = data[:3] if isinstance(data, list) else data
        # 找 6770 力積電
        row_6770 = next((row for row in (data if isinstance(data, list) else []) if row.get("Code") == "6770"), None)
        results["tpex"] = {
            "status": r.status_code,
            "total_count": len(data) if isinstance(data, list) else "N/A",
            "sample_keys": list(sample[0].keys()) if isinstance(sample, list) and sample else [],
            "sample_3rows": sample,
            "sample_6770": row_6770,
        }
    except Exception as e:
        results["tpex"] = {"error": str(e)}

    return results

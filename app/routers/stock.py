from fastapi import APIRouter, HTTPException, Query
from app.services.stock_fetcher import get_stock_basic, get_stock_history, search_stock, DataSourceError
from app.utils.safe_convert import safe_int, safe_float

router = APIRouter(prefix="/api/stock", tags=["股票資料"])


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    results = search_stock(q)
    if not results:
        raise HTTPException(404, detail=f"找不到「{q}」相關股票")
    return {"results": results, "total": len(results)}


@router.get("/{code}")
async def get_basic(code: str):
    try:
        return get_stock_basic(code)
    except DataSourceError as e:
        raise HTTPException(503, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"資料取得失敗：{e}")


def _safe_round(v, decimals=2):
    """安全浮點轉換：NaN/inf/None 全回傳 None（前端顯示 --）"""
    f = safe_float(v, default=None)
    if f is None:
        return None
    return round(f, decimals)


@router.get("/{code}/history")
async def get_history(code: str):
    try:
        df = get_stock_history(code)
        records = []
        for date, row in df.iterrows():
            records.append({
                "date":   str(date),
                "open":   _safe_round(row["Open"]),
                "high":   _safe_round(row["High"]),
                "low":    _safe_round(row["Low"]),
                "close":  _safe_round(row["Close"]),
                "volume": safe_int(row["Volume"], 0),   # ← 修正：int() → safe_int()
                "ma20":   _safe_round(row["MA20"]),
                "ma60":   _safe_round(row["MA60"]),
                "ma120":  _safe_round(row["MA120"]),
                "ma240":  _safe_round(row["MA240"]),
            })
        return {"code": code, "klines": records, "count": len(records)}
    except DataSourceError as e:
        raise HTTPException(503, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"資料取得失敗：{e}")

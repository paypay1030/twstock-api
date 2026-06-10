from fastapi import APIRouter, HTTPException, Query
from app.services.stock_fetcher import get_stock_basic, get_stock_history, search_stock, DataSourceError

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


@router.get("/{code}/history")
async def get_history(code: str):
    try:
        df = get_stock_history(code)
        records = []
        for date, row in df.iterrows():
            def f(v):
                return None if (v != v) else round(float(v), 2)
            records.append({
                "date": str(date), "open": f(row["Open"]),
                "high": f(row["High"]), "low": f(row["Low"]),
                "close": f(row["Close"]), "volume": int(row["Volume"]),
                "ma20": f(row["MA20"]),   "ma60":  f(row["MA60"]),
                "ma120": f(row["MA120"]), "ma240": f(row["MA240"]),
            })
        return {"code": code, "klines": records, "count": len(records)}
    except DataSourceError as e:
        raise HTTPException(503, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"資料取得失敗：{e}")

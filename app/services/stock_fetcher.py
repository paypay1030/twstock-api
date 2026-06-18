"""
Yahoo Finance 資料抓取服務

環境區分：
  APP_ENV=development  → Yahoo Finance 失敗時使用 Mock Data（開發用）
  APP_ENV=production   → Yahoo Finance 失敗時回傳錯誤，不使用 Mock
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.core.config import get_settings
from app.core.cache import price_cache, history_cache
from app.utils.stock_list import get_stock_name

settings = get_settings()

_IS_PROD = settings.app_env == "production"

# ── Mock 資料（僅開發環境使用）──────────────────────────────
_MOCK_DATA = {
    "6770": {"name": "力積電",  "price": 55.20, "high52": 72.30, "low52": 42.50, "change": -1.80},
    "2330": {"name": "台積電",  "price": 920.0, "high52": 1080.0,"low52": 700.0, "change": 12.0},
    "2454": {"name": "聯發科",  "price": 1160.0,"high52": 1300.0,"low52": 850.0, "change": 25.0},
    "2317": {"name": "鴻海",    "price": 185.0, "high52": 220.0, "low52": 140.0, "change": -2.0},
    "2303": {"name": "聯電",    "price": 52.0,  "high52": 68.0,  "low52": 40.0,  "change": 0.5},
    # ETF 範例（與一般股票同級處理，無特殊邏輯）
    "0050":   {"name": "元大台灣50",     "price": 185.0, "high52": 198.0, "low52": 150.0, "change": 1.2},
    "0056":   {"name": "元大高股息",     "price": 38.5,  "high52": 41.2,  "low52": 33.0,  "change": -0.15},
    "00878":  {"name": "國泰永續高股息", "price": 22.3,  "high52": 24.5,  "low52": 19.8,  "change": 0.05},
    "006208": {"name": "富邦台50",       "price": 95.6,  "high52": 102.0, "low52": 80.0,  "change": 0.8},
}


class DataSourceError(Exception):
    """資料來源無法取得時拋出"""
    pass


def _to_yf_symbol(code: str) -> tuple[str, str]:
    """轉換台股代號為 Yahoo Finance 格式，自動判斷上市/上櫃"""
    code = code.strip().upper()
    for suffix, market in [(".TW", "上市"), (".TWO", "上櫃")]:
        try:
            symbol = f"{code}{suffix}"
            h = yf.Ticker(symbol).history(period="2d")
            if not h.empty:
                return symbol, market
        except Exception:
            continue
    raise DataSourceError(f"找不到股票代號：{code}，請確認代號是否正確")


def get_stock_basic(code: str) -> dict:
    """
    取得股票基本資訊
    生產環境：失敗則拋出 DataSourceError
    開發環境：失敗則回傳 Mock Data
    """
    cache_key = f"basic:{code}"
    if cache_key in price_cache:
        return price_cache[cache_key]

    try:
        symbol, market = _to_yf_symbol(code)
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="2d")
        info   = ticker.fast_info

        if hist.empty:
            raise DataSourceError(f"{code} 無法取得交易資料")

        today  = hist.iloc[-1]
        prev   = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
        price  = float(today["Close"])
        prev_c = float(prev["Close"])
        change = round(price - prev_c, 2)

        name = get_stock_name(code) or _get_yf_name(ticker, code)

        result = {
            "symbol":        symbol,
            "code":          code,
            "name":          name,
            "market":        market,
            "current_price": price,
            "change":        change,
            "change_pct":    round(change / prev_c * 100, 2) if prev_c else 0,
            "volume":        int(today["Volume"] // 1000),
            "week52_high":   round(float(info.year_high), 2),
            "week52_low":    round(float(info.year_low),  2),
        }
        price_cache[cache_key] = result
        return result

    except DataSourceError as e:
        if _IS_PROD:
            raise
        return _mock_basic(code)  # 開發環境 fallback
    except Exception as e:
        if _IS_PROD:
            raise DataSourceError(f"資料取得失敗：{code}，請稍後再試") from e
        return _mock_basic(code)


def get_stock_history(code: str) -> pd.DataFrame:
    """
    取得近 N 年日 K 資料
    生產環境：失敗則拋出 DataSourceError
    開發環境：失敗則回傳 Mock Data
    """
    cache_key = f"history:{code}"
    if cache_key in history_cache:
        return history_cache[cache_key]

    try:
        symbol, _ = _to_yf_symbol(code)
        end   = datetime.today()
        start = end - timedelta(days=365 * settings.history_years)
        df = yf.Ticker(symbol).history(start=start, end=end)

        if df.empty:
            raise DataSourceError(f"{code} 歷史資料為空")

        df = _process_df(df)
        history_cache[cache_key] = df
        return df

    except DataSourceError as e:
        if _IS_PROD:
            raise
        return _mock_history(code)  # 開發環境 fallback
    except Exception as e:
        if _IS_PROD:
            raise DataSourceError(f"歷史資料取得失敗：{code}") from e
        return _mock_history(code)


def search_stock(query: str) -> list[dict]:
    """搜尋股票（代號或名稱），使用完整股票清單"""
    from app.utils.stock_list import search_stocks
    return search_stocks(query)


def _get_yf_name(ticker, code: str) -> str:
    try:
        return ticker.info.get("longName") or ticker.info.get("shortName") or code
    except Exception:
        return code


def _process_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index).date
    df.index.name = "Date"
    df["MA20"]  = df["Close"].rolling(20).mean().round(2)
    df["MA60"]  = df["Close"].rolling(60).mean().round(2)
    df["MA120"] = df["Close"].rolling(120).mean().round(2)
    df["MA240"] = df["Close"].rolling(240).mean().round(2)
    df["TR"]    = np.maximum(
        df["High"] - df["Low"],
        np.maximum(abs(df["High"] - df["Close"].shift(1)),
                   abs(df["Low"]  - df["Close"].shift(1))))
    df["ATR14"] = df["TR"].rolling(14).mean().round(2)
    df["Volume"] = (df["Volume"] // 1000).astype(int)
    return df


# ── Mock（僅開發環境，_IS_PROD=False 才會執行到）────────────

def _mock_basic(code: str) -> dict:
    m = _MOCK_DATA.get(code, {
        "name": get_stock_name(code) or f"股票{code}",
        "price": 100.0, "high52": 120.0, "low52": 80.0, "change": 0.0
    })
    price, change = m["price"], m["change"]
    prev = price - change or 1
    return {
        "symbol": f"{code}.TW", "code": code,
        "name": m.get("name") or get_stock_name(code) or code,
        "market": "上市", "current_price": price,
        "change": change, "change_pct": round(change / prev * 100, 2),
        "volume": 25000, "week52_high": m["high52"], "week52_low": m["low52"],
        "_mock": True,
        "_warning": "開發模式：顯示模擬資料，非真實市場數據"
    }


def _mock_history(code: str) -> pd.DataFrame:
    np.random.seed(hash(code) % 2**31)
    m    = _MOCK_DATA.get(code, {"price": 100.0})
    base = m["price"]
    n    = 756
    dates = pd.bdate_range(end=datetime.today(), periods=n)

    # 隨機漫步，最後 30 根收斂到 base（確保 VP 在現價附近有量）
    prices = [base * 0.75]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0.0004, 0.019)))
    prices = np.array(prices)
    for i in range(1, 31):
        alpha = i / 30
        prices[-31 + i] = prices[-31 + i] * (1 - alpha) + base * alpha
    prices = np.clip(prices, base * 0.35, base * 2.0)

    highs = prices * (1 + np.abs(np.random.normal(0.012, 0.008, n)))
    lows  = prices * (1 - np.abs(np.random.normal(0.012, 0.008, n)))
    opens = np.concatenate([[prices[0]], prices[:-1]])
    vols  = np.random.randint(5000, 30000, n)
    # 現價附近量放大（模擬籌碼集中）
    for i in range(n):
        if abs(prices[i] - base) / base < 0.08:
            vols[i] = int(vols[i] * 2.5)

    df = pd.DataFrame({
        "Open": np.round(opens, 2), "High": np.round(highs, 2),
        "Low":  np.round(lows,  2), "Close": np.round(prices, 2),
        "Volume": vols
    }, index=[d.date() for d in dates])
    df.index.name = "Date"
    df["MA20"]  = df["Close"].rolling(20).mean().round(2)
    df["MA60"]  = df["Close"].rolling(60).mean().round(2)
    df["MA120"] = df["Close"].rolling(120).mean().round(2)
    df["MA240"] = df["Close"].rolling(240).mean().round(2)
    df["TR"]    = np.maximum(
        df["High"] - df["Low"],
        np.maximum(abs(df["High"] - df["Close"].shift(1)),
                   abs(df["Low"]  - df["Close"].shift(1))))
    df["ATR14"] = df["TR"].rolling(14).mean().round(2)
    return df

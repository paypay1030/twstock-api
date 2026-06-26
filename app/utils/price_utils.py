"""
價格工具函數 + 台股靜態代號對照表（常見股票）
"""
import math


def round_to_tick(price: float, fallback: float = 0.0) -> float:
    """
    依台股升降單位四捨五入
    10以下：0.01　10~50：0.05　50~100：0.1
    100~500：0.5　500~1000：1　1000以上：5

    ETF 防呆：price 為 NaN / inf / 負數時回傳 fallback（預設 0.0）
    """
    # ── 防呆：任何非有限正數一律回傳 fallback ──
    if price is None:
        return fallback
    try:
        p = float(price)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(p) or math.isinf(p) or p <= 0:
        return fallback

    if p < 10:
        tick = 0.01
    elif p < 50:
        tick = 0.05
    elif p < 100:
        tick = 0.1
    elif p < 500:
        tick = 0.5
    elif p < 1000:
        tick = 1.0
    else:
        tick = 5.0
    return round(round(p / tick) * tick, 2)


def pct_diff(a: float, b: float) -> float:
    """計算兩價格的百分比差距（防呆：b=0 或 NaN 回傳 0.0）"""
    try:
        if not b or math.isnan(float(b)) or math.isinf(float(b)):
            return 0.0
        result = (a - b) / b
        return 0.0 if math.isnan(result) or math.isinf(result) else result
    except Exception:
        return 0.0


# 常見台股對照表（可擴充或從外部 JSON 讀取）
STOCK_LIST = [
    {"code": "2330", "name": "台積電",  "market": "上市"},
    {"code": "2317", "name": "鴻海",    "market": "上市"},
    {"code": "2454", "name": "聯發科",  "market": "上市"},
    {"code": "2382", "name": "廣達",    "market": "上市"},
    {"code": "2308", "name": "台達電",  "market": "上市"},
    {"code": "2881", "name": "富邦金",  "market": "上市"},
    {"code": "2882", "name": "國泰金",  "market": "上市"},
    {"code": "2412", "name": "中華電",  "market": "上市"},
    {"code": "2303", "name": "聯電",    "market": "上市"},
    {"code": "2891", "name": "中信金",  "market": "上市"},
    {"code": "3711", "name": "日月光投控","market": "上市"},
    {"code": "2886", "name": "兆豐金",  "market": "上市"},
    {"code": "1301", "name": "台塑",    "market": "上市"},
    {"code": "1303", "name": "南亞",    "market": "上市"},
    {"code": "2002", "name": "中鋼",    "market": "上市"},
    {"code": "6770", "name": "力積電",  "market": "上市"},
    {"code": "3218", "name": "大學光",  "market": "上市"},
    {"code": "2379", "name": "瑞昱",    "market": "上市"},
    {"code": "3008", "name": "大立光",  "market": "上市"},
    {"code": "2357", "name": "華碩",    "market": "上市"},
    {"code": "2395", "name": "研華",    "market": "上市"},
    {"code": "4938", "name": "和碩",    "market": "上市"},
    {"code": "2207", "name": "和泰車",  "market": "上市"},
    {"code": "5880", "name": "合庫金",  "market": "上市"},
    {"code": "2884", "name": "玉山金",  "market": "上市"},
]

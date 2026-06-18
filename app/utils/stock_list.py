"""
台股完整代號清單管理（含 ETF）

來源：twstock 套件
  - 一般股票：4 位數字代號
  - ETF：可能是 4~6 位數字，或含英文字尾（主動式 ETF，如 00981A）
本地快取為 stock_list.json
支援：代號搜尋、名稱模糊搜尋

ETF 與一般股票視為同級商品，不額外區分查詢邏輯，
僅在回應中標記 instrument_type 供前端顯示參考（非必要欄位）。

架構彈性：
  - JSON 檔可獨立更新，不需修改程式碼
  - 每次啟動載入一次，記憶體常駐
  - 提供 refresh_list() 供手動或定期更新
"""
import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_LIST_PATH = _BASE_DIR / "stock_list.json"

# 台股代號格式：2~6 位，可包含數字與結尾英文字母（如 00981A、00687B）
# 一般股票：4 位數字（如 2330）
# ETF：4~6 位數字，可選 1 位英文字尾（如 0050、00878、006208、00981A）
_CODE_PATTERN = re.compile(r"^[0-9]{2,6}[A-Z]?$")

# 排除衍生性商品雜訊（權證等），只保留可長期持有的投資標的
# 股票、ETF、特別股、ETN、TDR、REITs 等視為同級商品
_EXCLUDED_TYPES = {"上市認購(售)權證", "上櫃認購(售)權證"}


def is_valid_code_format(code: str) -> bool:
    """
    驗證代號格式是否合理（不限制只能 4 位數字）
    允許：2330、0050、00878、006208、00981A、00687B 等
    """
    return bool(_CODE_PATTERN.match(code.strip().upper()))


def _load_from_file() -> dict:
    if _LIST_PATH.exists():
        with open(_LIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"listed": [], "otc": []}


def _build_from_twstock() -> dict:
    """
    從 twstock 套件即時取得完整清單（含 ETF）

    twstock.codes 的 value 物件含 type 欄位，
    可能值包含："股票"、"ETF"、"ETN"、"受益證券" 等。
    這裡不依賴 type 篩選，只用代號格式驗證，
    確保未來任何新型態的台股代號（即使 twstock 沒分類好）也能被收錄。
    """
    try:
        import twstock
        result = {"listed": [], "otc": []}
        for code, info in twstock.codes.items():
            code_upper = code.strip().upper()

            # 用格式驗證取代舊的「4位數字限定」邏輯
            if not is_valid_code_format(code_upper):
                continue

            market = str(getattr(info, "market", ""))
            name   = str(getattr(info, "name", ""))
            inst_type = str(getattr(info, "type", "")) or "股票"
            if not name:
                continue
            # 排除權證等衍生性商品，只保留股票 / ETF / 特別股 / ETN / TDR / REITs 等
            if inst_type in _EXCLUDED_TYPES:
                continue

            entry = {"code": code_upper, "name": name, "type": inst_type}

            # twstock 的 market 欄位實際值為中文："上市"、"上市臺灣創新板"、"上櫃"
            if "上櫃" in market:
                result["otc"].append(entry)
            elif "上市" in market:
                result["listed"].append(entry)
        return result
    except Exception as e:
        logger.warning(f"twstock 載入失敗：{e}")
        return {"listed": [], "otc": []}


# ── 快取（程式啟動時載入一次）──────────────────────────────

class _StockListCache:
    def __init__(self):
        self._data: dict = {}
        self._index: dict[str, dict] = {}   # code → entry（O(1) 查詢）
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._data = _load_from_file()
        self._build_index()
        self._loaded = True
        logger.info(f"股票清單載入完成，共 {len(self._index)} 筆（含 ETF）")

    def _build_index(self):
        self._index = {}
        for entry in self._data.get("listed", []):
            self._index[entry["code"]] = {**entry, "market": "上市"}
        for entry in self._data.get("otc", []):
            self._index[entry["code"]] = {**entry, "market": "上櫃"}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        self._ensure_loaded()
        query = query.strip().upper()
        if not query:
            return []
        results = []

        # 完全匹配代號優先（包含 ETF 含字母代號，如 00981A）
        if query in self._index:
            results.append(self._index[query])

        # 前綴匹配代號（搜尋 "0087" 會找到 00878）
        for code, entry in self._index.items():
            if code != query and code.startswith(query):
                results.append(entry)
                if len(results) >= limit:
                    return results

        # 名稱包含搜尋（原樣比對，因中文不需大小寫轉換）
        original_query = query  # 保留原輸入做中文比對
        for entry in self._index.values():
            if entry not in results and original_query in entry["name"]:
                results.append(entry)
                if len(results) >= limit:
                    break

        return results[:limit]

    def get_by_code(self, code: str) -> Optional[dict]:
        self._ensure_loaded()
        return self._index.get(code.strip().upper())

    def refresh(self):
        """重新從 twstock 取得最新清單並寫入 JSON"""
        new_data = _build_from_twstock()
        if new_data["listed"] or new_data["otc"]:
            with open(_LIST_PATH, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
            self._data = new_data
            self._build_index()
            self._loaded = True
            logger.info(f"股票清單已更新：{len(self._index)} 筆（含 ETF）")
        else:
            logger.warning("更新失敗，保留原清單")

    @property
    def total(self) -> int:
        self._ensure_loaded()
        return len(self._index)


# 全域單例
stock_list_cache = _StockListCache()


def search_stocks(query: str, limit: int = 10) -> list[dict]:
    return stock_list_cache.search(query, limit)


def get_stock_name(code: str) -> str:
    entry = stock_list_cache.get_by_code(code)
    return entry["name"] if entry else code


def refresh_stock_list():
    stock_list_cache.refresh()

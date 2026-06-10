"""
台股完整代號清單管理

來源：twstock 套件（上市 1057 + 上櫃 880）
本地快取為 stock_list.json
支援：代號搜尋、名稱模糊搜尋

架構彈性：
  - JSON 檔可獨立更新，不需修改程式碼
  - 每次啟動載入一次，記憶體常駐
  - 提供 refresh_list() 供手動或定期更新
"""
import json
import os
import logging
from pathlib import Path
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# JSON 路徑：優先找專案根目錄，再找 app/utils 同層
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_LIST_PATH = _BASE_DIR / "stock_list.json"


def _load_from_file() -> dict:
    if _LIST_PATH.exists():
        with open(_LIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"listed": [], "otc": []}


def _build_from_twstock() -> dict:
    """從 twstock 套件即時取得清單（作為備援或更新用）"""
    try:
        import twstock
        result = {"listed": [], "otc": []}
        for code, info in twstock.codes.items():
            if not code.isdigit() or len(code) != 4:
                continue
            market = str(getattr(info, "market", ""))
            name   = str(getattr(info, "name", ""))
            if not name:
                continue
            entry = {"code": code, "name": name}
            if "TWSE" in market:
                result["listed"].append(entry)
            elif "OTC" in market or "TPEx" in market:
                result["otc"].append(entry)
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
        self._data  = _load_from_file()
        self._build_index()
        self._loaded = True
        total = len(self._index)
        logger.info(f"股票清單載入完成，共 {total} 筆")

    def _build_index(self):
        self._index = {}
        for entry in self._data.get("listed", []):
            self._index[entry["code"]] = {**entry, "market": "上市"}
        for entry in self._data.get("otc", []):
            self._index[entry["code"]] = {**entry, "market": "上櫃"}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        self._ensure_loaded()
        query = query.strip()
        if not query:
            return []
        results = []
        # 完全匹配代號優先
        if query in self._index:
            results.append(self._index[query])
        # 前綴匹配代號
        for code, entry in self._index.items():
            if code != query and code.startswith(query):
                results.append(entry)
                if len(results) >= limit:
                    return results
        # 名稱包含搜尋
        for entry in self._index.values():
            if entry not in results and query in entry["name"]:
                results.append(entry)
                if len(results) >= limit:
                    break
        return results[:limit]

    def get_by_code(self, code: str) -> Optional[dict]:
        self._ensure_loaded()
        return self._index.get(code)

    def refresh(self):
        """重新從 twstock 取得最新清單並寫入 JSON"""
        new_data = _build_from_twstock()
        if new_data["listed"] or new_data["otc"]:
            with open(_LIST_PATH, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
            self._data = new_data
            self._build_index()
            self._loaded = True
            logger.info(f"股票清單已更新：{len(self._index)} 筆")
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

"""
簡易記憶體快取
TTL 到期自動失效，避免頻繁呼叫 Yahoo Finance
"""
from cachetools import TTLCache
from app.core.config import get_settings

settings = get_settings()

# 現價快取：TTL 5 分鐘，最多 200 個 key
price_cache: TTLCache = TTLCache(
    maxsize=200,
    ttl=settings.cache_ttl_price
)

# 歷史 K 線快取：TTL 1 小時，最多 100 個 key
history_cache: TTLCache = TTLCache(
    maxsize=100,
    ttl=settings.cache_ttl_history
)

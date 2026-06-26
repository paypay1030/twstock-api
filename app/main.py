"""
我的持股管家 API — FastAPI 主程式
"""
import math
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import get_settings
from app.routers import stock, analysis

settings = get_settings()


class SafeJSONResponse(JSONResponse):
    """
    自訂 JSON Response：將 NaN / Infinity / -Infinity 轉為 null。

    背景：Python json 模組預設允許 float('nan') / float('inf') 輸出為
    JavaScript 識別符 NaN / Infinity，但這不是合法的 JSON（RFC 8259），
    會導致前端 JSON.parse 失敗或 React 渲染 NaN 時崩潰。
    ETF 因成立時間短、部分欄位缺失，特別容易出現此類值。
    """

    def render(self, content) -> bytes:
        def _sanitize(obj):
            if isinstance(obj, float):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(item) for item in obj]
            return obj

        sanitized = _sanitize(content)
        return json.dumps(sanitized, ensure_ascii=False).encode("utf-8")


app = FastAPI(
    title=settings.app_name,
    description="台股個人投資分析助手 API。所有分析均為機率與風險評估，不保證股價預測。",
    version="0.1.0",
    default_response_class=SafeJSONResponse,   # 全域套用：所有回應自動清理 NaN/Inf
)

# CORS（允許前端跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載 Router
app.include_router(stock.router)
app.include_router(analysis.router)


@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "status":  "running",
        "disclaimer": "所有分析均為機率與風險評估，不預測股價。"
    }


@app.get("/health")
async def health():
    return {"status": "ok"}

# ── Logging 設定（確保 Railway 能看到完整錯誤）────────────────
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

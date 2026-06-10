"""
我的持股管家 API — FastAPI 主程式
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.routers import stock, analysis

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="台股個人投資分析助手 API。所有分析均為機率與風險評估，不保證股價預測。",
    version="0.1.0"
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

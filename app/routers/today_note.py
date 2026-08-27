"""
GET /api/today-note
今日市場小筆記 endpoint
"""
import logging
from fastapi import APIRouter
from app.services.today_note import generate_today_note

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/today-note")
async def get_today_note():
    """
    回傳今日市場摘要與建議。
    資料來源：Yahoo Finance ^TWII 加權指數。
    資料失敗時回傳 source='unavailable'，不使用假數字。
    """
    return generate_today_note()

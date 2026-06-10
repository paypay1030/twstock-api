"""
分析 Router

原則：分析結果不受個人持股成本影響。
      支撐壓力、燈號、風險等級純技術分析。
"""
from fastapi import APIRouter, HTTPException
from app.services.stock_fetcher import get_stock_basic, get_stock_history, DataSourceError
from app.services.support_resistance import calculate_sr
from app.services.risk_engine import calculate_signal, calculate_risk
from app.services.decision_card import generate_decision_card

router = APIRouter(prefix="/api/analysis", tags=["分析"])


@router.post("/{code}")
@router.get("/{code}")
async def analyze(code: str):
    """
    純技術分析，不接受個人成本作為輸入。
    個人持股資訊由前端疊加顯示，不影響分析結果。
    """
    try:
        basic = get_stock_basic(code)
        df    = get_stock_history(code)
        price = basic["current_price"]

        sr_result = calculate_sr(df, price)
        signal    = calculate_signal(
            price,
            sr_result.support_levels,
            sr_result.resistance_levels,
            sr_result.stop_loss
        )
        # 風險等級：無成本資訊，純技術面（支撐距離 + ATR）
        risk = calculate_risk(price, None, sr_result.support_levels, df)
        card = generate_decision_card(
            code=code,
            name=basic["name"],
            current_price=price,
            sr_result=sr_result,
            signal=signal,
            risk=risk,
        )

        return {
            "basic":          basic,
            "sr_result":      sr_result.model_dump(),
            "decision_card":  card.model_dump(),
            "buy_zone":       _buy_zone(sr_result, price),
            "sell_zone":      _sell_zone(sr_result, price),
            "stop_loss_zone": [sr_result.stop_loss, round(sr_result.stop_loss * 0.98, 2)],
            "disclaimer":     "所有分析均為機率與風險評估，不保證未來股價走勢。"
        }
    except DataSourceError as e:
        raise HTTPException(503, detail=str(e))
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"分析失敗：{e}")


def _buy_zone(sr, price):
    return [sr.support_levels[0].range_low, sr.support_levels[0].range_high] \
        if sr.support_levels else [round(price * 0.95, 2), round(price * 0.97, 2)]


def _sell_zone(sr, price):
    return [sr.resistance_levels[0].range_low, sr.resistance_levels[0].range_high] \
        if sr.resistance_levels else [round(price * 1.05, 2), round(price * 1.08, 2)]

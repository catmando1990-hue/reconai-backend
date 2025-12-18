# app/routers/feedback.py

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import stores

router = APIRouter(prefix="/feedback", tags=["feedback"])

Label = Literal["business", "personal", "uncertain"]


class MerchantFeedbackIn(BaseModel):
    merchant: str = Field(..., min_length=1)
    label: Label


@router.post("/merchant")
def set_merchant_override(payload: MerchantFeedbackIn):
    try:
        stores.set_merchant_feedback(payload.merchant, payload.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "merchant": payload.merchant.strip(), "label": payload.label}


@router.get("/merchant")
def get_merchant_override(merchant: str):
    label = stores.get_merchant_feedback(merchant)
    return {"merchant": merchant.strip(), "label": label}

# app/routers/feedback.py

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import stores

router = APIRouter(prefix="/feedback", tags=["feedback"])

Label = Literal["business", "personal", "uncertain"]


class MerchantFeedbackIn(BaseModel):
    merchant: str = Field(..., min_length=1)

    # Accept either key from the client:
    # - label (our preferred API field)
    # - correct_label (matches your DB column name + what you're sending now)
    label: Optional[Label] = None
    correct_label: Optional[Label] = None


@router.post("/merchant")
def set_merchant_override(payload: MerchantFeedbackIn):
    label = payload.label or payload.correct_label
    if label not in ("business", "personal", "uncertain"):
        raise HTTPException(
            status_code=422,
            detail="Provide 'label' or 'correct_label' with one of: business, personal, uncertain",
        )

    try:
        stores.set_merchant_feedback(payload.merchant, label)
    except ValueError as e:
        # Bad user input should NOT be a 500
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # If something truly unexpected happens, show detail for debugging
        raise HTTPException(status_code=500, detail=f"Failed to save merchant feedback: {e}")

    return {"status": "ok", "merchant": payload.merchant.strip(), "label": label}


@router.get("/merchant")
def get_merchant_override(merchant: str):
    try:
        label = stores.get_merchant_feedback(merchant)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read merchant feedback: {e}")

    return {"merchant": merchant.strip(), "label": label}

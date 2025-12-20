from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.reconai_core.merchant_recognition import MerchantRecognizer
import pandas as pd

router = APIRouter(prefix="/api/merchant", tags=["merchant"])

# Initialize recognizer
recognizer = MerchantRecognizer()
try:
    recognizer.load_model()
except:
    print("No trained model found - using pattern matching only")

class MerchantRequest(BaseModel):
    description: str

@router.post("/recognize")
async def recognize_merchant(request: MerchantRequest):
    """Recognize merchant from bank description"""
    result = recognizer.recognize(request.description)
    
    return {
        "merchant": result.clean_name,
        "category": result.category,
        "merchant_type": result.merchant_type,
        "confidence": result.confidence,
        "reasoning": result.reasoning
    }

@router.post("/recognize-batch")
async def recognize_batch(descriptions: list[str]):
    """Recognize multiple merchants at once"""
    results = []
    for desc in descriptions:
        result = recognizer.recognize(desc)
        results.append({
            "original": desc,
            "merchant": result.clean_name,
            "category": result.category,
            "confidence": result.confidence
        })
    
    return {"results": results}

@router.post("/train")
async def train_model(training_data: list[dict]):
    """Train merchant recognition model"""
    df = pd.DataFrame(training_data)
    metrics = recognizer.train(df)
    
    return {
        "status": "trained",
        "accuracy": metrics["test_accuracy"],
        "samples": metrics["n_samples"]
    }
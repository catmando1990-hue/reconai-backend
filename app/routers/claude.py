from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.reconai_core.claude_chat import chat_with_claude

router = APIRouter(prefix="/api/claude", tags=["claude"])

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[Message]] = None

class ChatResponse(BaseModel):
    response: str

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        # Convert conversation history to the format Claude expects
        history = None
        if request.conversation_history:
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.conversation_history
            ]
        
        # Get Claude's response
        claude_response = chat_with_claude(request.message, history)
        
        return ChatResponse(response=claude_response)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""
backend/routers/chat.py

Exposes ChatAgent (Feature 16) as an API endpoint. Register this in
main.py the same way ingest_router / ws_router / decoy_router are
registered — see integration notes below the router definition.

    from backend.routers.chat import router as chat_router
    ...
    app.include_router(chat_router, tags=["Chat"])
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.chat_agent import ChatAgent

router = APIRouter()

_chat_agent = ChatAgent()


class ChatQuestion(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class ChatAnswer(BaseModel):
    answer: str
    cited_edge_ids: list[int]
    confidence: str


@router.post("/api/incidents/{incident_id}/chat", response_model=ChatAnswer)
async def ask_about_incident(incident_id: int, payload: ChatQuestion) -> ChatAnswer:
    """
    Ask a free-text question about a specific incident (e.g. "why did you
    block this IP?") and get an answer grounded in that incident's
    recorded decision-provenance graph.
    """
    try:
        result = await _chat_agent.answer(incident_id=incident_id, question=payload.question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat agent failed: {exc}") from exc

    return ChatAnswer(**result)

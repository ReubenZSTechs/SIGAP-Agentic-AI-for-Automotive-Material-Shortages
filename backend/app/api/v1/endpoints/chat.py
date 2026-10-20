import json

from typing import Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.chatbot.service import ChatService, ChatUnavailable, get_chat_service
from app.config import settings
from app.core.exceptions import AppError

router = APIRouter()

THREAD_ID = r"^[A-Za-z0-9_-]{8,64}$"


class ResumeRequest(BaseModel):
    """Answer to a PO confirmation card."""
    action_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    decision: Literal["approve", "reject"]


class ChatRequest(BaseModel):
    """Either a new `message` or a `resume` answer to a pending PO confirmation."""
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    thread_id: str = Field(pattern=THREAD_ID)
    resume: ResumeRequest | None = None

    @model_validator(mode="after")
    def _one_of(self):
        if (self.message is None) == (self.resume is None):
            raise ValueError("Kirim tepat salah satu: message atau resume")
        if self.message is not None and not self.message.strip():
            raise ValueError("message kosong")
        return self

    def args(self) -> tuple[str | None, str, dict | None]:
        return (self.message.strip() if self.message else None, self.thread_id,
                self.resume.model_dump() if self.resume else None)


def service() -> ChatService:
    """Resolves the chat service or maps misconfiguration to HTTP 503."""
    try:
        return get_chat_service()
    except ChatUnavailable as e:
        raise AppError(503, str(e)) from e


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.get("/health")
def chat_health():
    """Whether SAP AI Core credentials are configured."""
    return {"configured": settings.aicore_configured}


@router.post("/stream")
def chat_stream(body: ChatRequest, svc: ChatService = Depends(service)):
    """Server-Sent Events: `progress`* then `final` (or `error`)."""
    return StreamingResponse((_sse(e) for e in svc.stream(*body.args())),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("")
def chat(body: ChatRequest, svc: ChatService = Depends(service)):
    """Non-streaming variant: returns the final (or error) event."""
    return svc.run(*body.args())


@router.get("/{thread_id}/history")
def chat_history(thread_id: str = Path(pattern=THREAD_ID), svc: ChatService = Depends(service)):
    """Messages of a conversation thread (+ PO action cards with current status), for restoring the UI."""
    return {"thread_id": thread_id, "messages": svc.history(thread_id), "actions": svc.actions(thread_id)}

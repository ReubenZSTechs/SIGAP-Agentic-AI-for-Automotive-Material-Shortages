import json

from typing import Literal

from fastapi import APIRouter, Depends, Header, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.chatbot import threads
from app.chatbot.service import ChatService, ChatUnavailable, get_chat_service
from app.config import settings
from app.core.exceptions import AppError

router = APIRouter()

THREAD_ID = r"^[A-Za-z0-9_-]{8,64}$"
CLIENT_ID = r"^[A-Za-z0-9_-]{8,64}$"      # id acak per browser (header X-Client-Id); lihat app/models/chat_thread.py


MAX_FORM_BYTES = 50_000


class ResumeRequest(BaseModel):
    """Answer to a confirmation card (approve/reject) or to a chat form (submit with `values`, or reject)."""
    action_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    decision: Literal["approve", "reject", "submit"]
    values: dict | None = None

    @model_validator(mode="after")
    def _values_only_on_submit(self):
        if (self.decision == "submit") != (self.values is not None):
            raise ValueError("values wajib (hanya) untuk decision=submit")
        if self.values is not None and len(json.dumps(self.values, default=str)) > MAX_FORM_BYTES:
            raise ValueError("Isian formulir terlalu besar")
        return self


class ChatRequest(BaseModel):
    """Either a new `message` or a `resume` answer to a pending card/form. `language` = the UI language
    the user picked; when set it decides the reply language instead of auto-detection."""
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    thread_id: str = Field(pattern=THREAD_ID)
    resume: ResumeRequest | None = None
    language: Literal["id", "en"] | None = None

    @model_validator(mode="after")
    def _one_of(self):
        if (self.message is None) == (self.resume is None):
            raise ValueError("Kirim tepat salah satu: message atau resume")
        if self.message is not None and not self.message.strip():
            raise ValueError("message kosong")
        return self

    def args(self) -> tuple[str | None, str, dict | None, str | None]:
        return (self.message.strip() if self.message else None, self.thread_id,
                self.resume.model_dump() if self.resume else None, self.language)


def service() -> ChatService:
    """Resolves the chat service or maps misconfiguration to HTTP 503."""
    try:
        return get_chat_service()
    except ChatUnavailable as e:
        raise AppError(503, str(e)) from e


def owner_id(x_client_id: str | None = Header(default=None, pattern=CLIENT_ID)) -> str | None:
    """Browser that owns the conversation (optional: clients without the header just are not listed)."""
    return x_client_id


def required_owner_id(x_client_id: str = Header(pattern=CLIENT_ID)) -> str:
    """Same, but required: the history list and deletes are always scoped to one browser."""
    return x_client_id


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.get("/health")
def chat_health():
    """Whether SAP AI Core credentials are configured."""
    return {"configured": settings.aicore_configured}


@router.post("/stream")
def chat_stream(body: ChatRequest, svc: ChatService = Depends(service), owner: str | None = Depends(owner_id)):
    """Server-Sent Events: `progress`* then `final` (or `error`)."""
    return StreamingResponse((_sse(e) for e in svc.stream(*body.args(), owner=owner)),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("")
def chat(body: ChatRequest, svc: ChatService = Depends(service), owner: str | None = Depends(owner_id)):
    """Non-streaming variant: returns the final (or error) event."""
    return svc.run(*body.args(), owner=owner)


@router.get("/threads")
def chat_threads(owner: str = Depends(required_owner_id), db: Session = Depends(get_db)):
    """Past conversations of this browser, newest first (history list). Open one with `GET /{thread_id}/history`."""
    return {"threads": [{"thread_id": t.thread_id, "title": t.title, "created_at": t.created_at,
                         "updated_at": t.updated_at} for t in threads.list_for(db, owner)]}


@router.delete("/threads/{thread_id}", status_code=204)
def delete_chat_thread(thread_id: str = Path(pattern=THREAD_ID), owner: str = Depends(required_owner_id),
                       db: Session = Depends(get_db), svc: ChatService = Depends(service)):
    """Deletes one conversation of this browser (messages + list entry). Someone else's thread is a plain 404."""
    if not threads.is_owned(db, thread_id, owner):
        raise AppError(404, "Percakapan tidak ditemukan")
    svc.delete_thread(thread_id)


@router.delete("/threads")
def delete_all_chat_threads(owner: str = Depends(required_owner_id), db: Session = Depends(get_db),
                            svc: ChatService = Depends(service)):
    """Deletes every conversation of this browser."""
    ids = threads.owned_ids(db, owner)
    for thread_id in ids:
        svc.delete_thread(thread_id)
    return {"deleted": len(ids)}


@router.get("/{thread_id}/history")
def chat_history(thread_id: str = Path(pattern=THREAD_ID), svc: ChatService = Depends(service)):
    """Messages of a conversation thread (+ PO action cards with current status), for restoring the UI."""
    return {"thread_id": thread_id, "messages": svc.history(thread_id), "actions": svc.actions(thread_id)}

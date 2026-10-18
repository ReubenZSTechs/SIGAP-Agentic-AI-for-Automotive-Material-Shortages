"""Chat service: owns the compiled graph and its Postgres checkpointer."""
import logging
import threading
from collections.abc import Iterator

from langchain_core.messages import AIMessage, HumanMessage

from app.chatbot.config_loader import load_registry
from app.chatbot.llm import build_agents, build_sap_clients
from app.config import settings
from configs.workflows.chat_graph import ERROR_TEXT, build_graph, new_turn

log = logging.getLogger(__name__)


class ChatUnavailable(RuntimeError):
    """The chatbot is not configured (missing SAP AI Core credentials)."""


class ChatService:
    """Runs conversation turns on a compiled graph with a checkpointer."""

    def __init__(self, graph):
        self.graph = graph

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def stream(self, message: str, thread_id: str) -> Iterator[dict]:
        """Yields progress events, then exactly one `final` (or `error`) event."""
        config = self._config(thread_id)
        try:
            for event in self.graph.stream(new_turn(message), config, stream_mode="custom"):
                yield event
            final = self.graph.get_state(config).values.get("final")
            yield {"type": "final", **final}
        except Exception as e:  # noqa: BLE001
            log.exception("chat turn failed (thread=%s)", thread_id)
            yield {"type": "error", "message": ERROR_TEXT["id"], "detail": f"{type(e).__name__}: {e}"}

    def run(self, message: str, thread_id: str) -> dict:
        """Runs one turn and returns the final event (or the error event)."""
        last = {}
        for event in self.stream(message, thread_id):
            last = event
        return last

    def history(self, thread_id: str) -> list[dict]:
        """Conversation so far as frontend messages."""
        values = self.graph.get_state(self._config(thread_id)).values or {}
        out = []
        for m in values.get("messages", []):
            if isinstance(m, HumanMessage):
                out.append({"role": "user", "blocks": [{"type": "text", "text": str(m.content)}]})
            elif isinstance(m, AIMessage):
                out.append({"role": "agent", "blocks": m.additional_kwargs.get("blocks")
                            or [{"type": "text", "text": str(m.content)}],
                            "meta": m.additional_kwargs.get("meta")})
        return out


_lock = threading.Lock()
_service: ChatService | None = None


def _checkpointer():
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    conninfo = settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1)
    pool = ConnectionPool(conninfo, max_size=5, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


def get_chat_service() -> ChatService:
    """FastAPI dependency: lazily builds the production service (SAP clients + PostgresSaver)."""
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                if not settings.aicore_configured:
                    raise ChatUnavailable("Chatbot belum dikonfigurasi: isi AICORE_AUTH_URL, AICORE_CLIENT_ID, "
                                          "AICORE_CLIENT_SECRET, dan AICORE_BASE_URL di backend/.env.")
                registry = load_registry()
                try:
                    clients = build_sap_clients(settings, registry)
                except Exception as e:  # noqa: BLE001
                    log.exception("cannot connect to SAP AI Core")
                    raise ChatUnavailable(f"Gagal terhubung ke SAP AI Core ({type(e).__name__}): {e}. "
                                          "Periksa nilai AICORE_* di backend/.env.") from e
                agents = build_agents(registry, clients)
                _service = ChatService(build_graph(agents, registry.chatbot, checkpointer=_checkpointer()))
    return _service

"""Chat service: owns the compiled graph and its Postgres checkpointer."""
import logging
import threading
from collections.abc import Iterator

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.chatbot import tracing
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

    def pending_action(self, thread_id: str) -> str | None:
        """Id of the automation proposal this thread is paused on (LangGraph interrupt), if any."""
        snapshot = self.graph.get_state(self._config(thread_id))
        interrupts = list(getattr(snapshot, "interrupts", ()) or ())
        if not interrupts:
            interrupts = [i for t in (snapshot.tasks or ()) for i in (getattr(t, "interrupts", ()) or ())]
        for it in interrupts:
            value = getattr(it, "value", None)
            if isinstance(value, dict) and value.get("action_id"):
                return value["action_id"]
        return None

    def stream(self, message: str | None, thread_id: str, resume: dict | None = None) -> Iterator[dict]:
        """Yields progress events, then exactly one `final` (or `error`) event.

        `resume={action_id, decision: approve|reject}` answers a pending confirmation card;
        `resume={action_id, decision: submit, values}` answers a pending chat form. A new `message` while a
        card or form is pending first marks it as superseded.
        """
        config = self._config(thread_id)
        trace = tracing.new_trace("chat", thread_id=thread_id)     # semua agent dalam giliran ini satu trace
        try:
            pending = self.pending_action(thread_id)
            if resume is not None:
                if pending != resume["action_id"]:
                    yield {"type": "error", "message": "Usulan ini sudah tidak menunggu konfirmasi.",
                           "detail": "no matching pending action"}
                    return
                graph_input = Command(resume={"decision": resume["decision"], "action_id": pending,
                                              "values": resume.get("values")})
            else:
                if pending:
                    self.graph.invoke(Command(resume={"decision": "superseded", "action_id": pending}), config)
                graph_input = new_turn(message, thread_id)
            events = iter(self.graph.stream(graph_input, config, stream_mode="custom"))
            while True:                                           # trace aktif per langkah, tidak melewati yield
                with tracing.activate(trace):
                    event = next(events, None)
                if event is None:
                    break
                yield event
            final = self.graph.get_state(config).values.get("final")
            yield {"type": "final", **final}
        except Exception as e:  # noqa: BLE001
            log.exception("chat turn failed (thread=%s)", thread_id)
            yield {"type": "error", "message": ERROR_TEXT["id"], "detail": f"{type(e).__name__}: {e}"}

    def run(self, message: str | None, thread_id: str, resume: dict | None = None) -> dict:
        """Runs one turn and returns the final event (or the error event)."""
        last = {}
        for event in self.stream(message, thread_id, resume):
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

    def actions(self, thread_id: str) -> dict:
        """PO action cards shown in this thread, with their current status from `automation_actions`."""
        from app.database import SessionLocal
        from app.models import AutomationAction
        from configs.workflows.automation_graph import UI_STATUS
        values = self.graph.get_state(self._config(thread_id)).values or {}
        cards = {}
        for m in values.get("messages", []):
            if isinstance(m, AIMessage):
                cards.update(m.additional_kwargs.get("actions") or {})
        if cards:
            with SessionLocal() as db:
                for aid, card in cards.items():
                    row = db.get(AutomationAction, aid)
                    if row is not None:
                        cards[aid] = {**card, "status": UI_STATUS[row.status]}
        return cards


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


_agents: tuple[dict, object] | None = None


def live_agents():
    """(agents, registry) bound to SAP AI Core, built once and shared by the chat and supplier services."""
    global _agents
    if _agents is None:
        with _lock:
            if _agents is None:
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
                _agents = (build_agents(registry, clients), registry)
    return _agents


def get_chat_service() -> ChatService:
    """FastAPI dependency: lazily builds the production service (SAP clients + PostgresSaver)."""
    global _service
    if _service is None:
        agents, registry = live_agents()
        with _lock:
            if _service is None:
                from app.supplier_chat.service import dispatch_in_background
                _service = ChatService(build_graph(agents, registry.chatbot, checkpointer=_checkpointer(),
                                                   automation_cfg=registry.automation,
                                                   on_supplier_work=dispatch_in_background))
    return _service

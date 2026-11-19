"""Agent Hub — browse every LLM agent call (input, prompt, output, retries, latency, tokens) and every
Postgres tool execution (arguments, SQL statements, result preview, latency).

    pip install -r backend/requirements-streamlit.txt
    streamlit run backend/streamlit_app/agent_hub.py

Talks only to the FastAPI backend (SIGAP_API_URL, default http://localhost:8000/api/v1), which records
each call in `agent_runs` and each tool execution in `tool_runs` (see docs/AGENT_TRACKING.md). One trace =
one chat turn, supplier message, manager reply or dispatch round; open a trace to follow its agents and
database tools step by step.
"""
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st

API = os.environ.get("SIGAP_API_URL", "http://localhost:8000/api/v1").rstrip("/")
TZ = ZoneInfo("Asia/Jakarta")
STATUS = {"ok": "✅ ok", "invalid": "⚠️ invalid", "error": "❌ error"}
KIND = {"read": "📖 baca", "sql": "🧮 SQL agent", "write": "✍️ tulis"}
VIEWS = ("Agent LLM", "Tool Postgres")
WORKFLOW = {"chat": "Chat Dashboard", "supplier": "Balasan supplier", "manager": "Manajer",
            "supplier_outreach": "Pesan keluar supplier", "hub_mission": "Misi Hub", "other": "Lainnya"}

st.set_page_config(page_title="Agent Hub · SIGAP", layout="wide")
client = httpx.Client(base_url=API, timeout=30.0)


def call(path: str, **params):
    try:
        r = client.get(path, params={k: v for k, v in params.items() if v not in (None, "", [])})
    except httpx.HTTPError as e:
        st.error(f"Backend tidak dapat dihubungi ({API}): {e}")
        st.stop()
    if r.status_code >= 400:
        st.error(f"GET {path} → HTTP {r.status_code}: {r.text[:300]}")
        st.stop()
    return r.json()


def local(ts: str | None) -> str:
    if not ts:
        return "–"
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%d %b %H:%M:%S")


def utc(d: date, end: bool = False) -> str:
    return datetime.combine(d, time.max if end else time.min, TZ).astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def preview(output, error) -> str:
    if error and not output:
        return error[:120]
    text = json.dumps(output, ensure_ascii=False) if output is not None else ""
    return text[:120] + ("…" if len(text) > 120 else "")


def pretty(text: str | None):
    """JSON input is shown as a tree; plain text (e.g. a raw message) as text."""
    try:
        st.json(json.loads(text))
    except (TypeError, ValueError):
        st.code(text or "", language=None, wrap_lines=True)


def counted(facet_list):
    """format_func for a multiselect: 'value (count)'."""
    counts = {f["value"]: f["count"] for f in facet_list}
    return lambda v: f"{v} ({counts.get(v, 0)})"


# ------------------------------------------------------------------ sidebar
st.session_state.setdefault("trace_id", "")
with st.sidebar:
    st.title("Agent Hub")
    st.caption(f"Sumber: {API}")
    view = st.radio("Tampilan", VIEWS, horizontal=True)
    agents, tools, kinds = [], [], []
    if view == "Agent LLM":
        facets = call("/agent-runs/facets")
        agents = st.multiselect("Agent", [f["value"] for f in facets["agents"]], format_func=counted(facets["agents"]),
                                placeholder="Semua agent")
    else:
        facets = call("/tool-runs/facets")
        tools = st.multiselect("Tool", [f["value"] for f in facets["tools"]], format_func=counted(facets["tools"]),
                               placeholder="Semua tool")
        kinds = st.multiselect("Jenis", list(KIND), format_func=KIND.get, placeholder="Semua jenis")
    workflows = st.multiselect("Alur", [f["value"] for f in facets["workflows"]],
                               format_func=lambda v: WORKFLOW.get(v, v), placeholder="Semua alur")
    statuses = st.multiselect("Status", list(STATUS), format_func=STATUS.get, placeholder="Semua status")
    today = datetime.now(TZ).date()
    period = st.date_input("Periode", (today - timedelta(days=7), today))
    q = st.text_input("Cari di input / output / SQL / error", placeholder="mis. Cipta Logam")
    st.session_state.trace_id = st.text_input("Trace id", st.session_state.trace_id).strip()
    limit = st.selectbox("Baris per halaman", [50, 100, 200, 500], index=1)
    page = st.number_input("Halaman", min_value=1, value=1, step=1)
    auto = st.toggle("Muat ulang otomatis (10 dtk)")
    if st.button("Muat ulang", width="stretch"):
        st.rerun()

since, until = (period if isinstance(period, tuple) and len(period) == 2 else (period, period)) if period else (None, None)


def period_params() -> dict:
    return {"since": utc(since) if since else None, "until": utc(until, end=True) if until else None}


def open_trace_button(trace_id: str):
    if not st.session_state.trace_id and st.button("Tampilkan semua langkah di trace ini", type="primary"):
        st.session_state.trace_id = trace_id
        st.rerun()


# ------------------------------------------------------------------ one trace: LLM calls + tool runs, by time
def trace_view(trace: str):
    llm = call("/agent-runs", trace_id=trace, limit=1000)["items"]
    tool = call("/tool-runs", trace_id=trace, limit=1000)["items"]
    steps = sorted([{**r, "_type": "llm"} for r in llm] + [{**r, "_type": "tool"} for r in tool],
                   key=lambda r: (r["created_at"], r["id"]))
    st.subheader(f"Trace {trace[:12]}…")
    first = steps[0] if steps else {}
    st.caption(f"{WORKFLOW.get(first.get('workflow'), first.get('workflow', ''))} · ref {first.get('ref') or {}} · "
               f"{len(llm)} panggilan agent + {len(tool)} eksekusi tool, urut waktu")
    if st.button("Tutup trace"):
        st.session_state.trace_id = ""
        st.rerun()
    if not steps:
        st.info("Trace ini kosong.")
        return
    df = pd.DataFrame([{
        "#": n + 1, "Waktu": local(r["created_at"]),
        "Jenis": "🤖 Agent LLM" if r["_type"] == "llm" else KIND.get(r["kind"], r["kind"]),
        "Nama": r["agent"] if r["_type"] == "llm" else r["tool"], "Status": STATUS.get(r["status"], r["status"]),
        "Latensi (ms)": r["latency_ms"],
        "Ringkasan": preview(r["output"], r["error"]) if r["_type"] == "llm"
        else (r["error"] or (f"{r['row_count']} baris" if r["row_count"] is not None else "ok")),
    } for n, r in enumerate(steps)])
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         key=f"trace-{trace}", column_config={"Ringkasan": st.column_config.TextColumn(width="large")})
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        st.caption("Pilih satu langkah untuk melihat detailnya.")
        return
    chosen = steps[rows[0]]
    (detail if chosen["_type"] == "llm" else tool_detail)(chosen["id"])


# ------------------------------------------------------------------ tool runs list
def tools_view():
    data = call("/tool-runs", tool=tools, kind=kinds, workflow=workflows, status=statuses, q=q,
                limit=limit, offset=(page - 1) * limit, **period_params())
    items = data["items"]
    st.subheader("Eksekusi tool Postgres")
    failed = sum(1 for r in items if r["status"] != "ok")
    lat = [r["latency_ms"] for r in items]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total (filter)", data["total"])
    c2.metric("Di halaman ini", len(items))
    c3.metric("Gagal", failed)
    c4.metric("Latensi median", f"{int(pd.Series(lat).median())} ms" if lat else "–")
    if not items:
        st.info("Tidak ada eksekusi tool untuk filter ini.")
        return
    df = pd.DataFrame([{
        "#": r["id"], "Waktu": local(r["created_at"]), "Tool": r["tool"], "Jenis": KIND.get(r["kind"], r["kind"]),
        "Alur": WORKFLOW.get(r["workflow"], r["workflow"]), "Status": STATUS.get(r["status"], r["status"]),
        "Latensi (ms)": r["latency_ms"], "Baris": "" if r["row_count"] is None else str(r["row_count"]),
        "Trace": r["trace_id"][:8], "Argumen": preview(r["args"], r["error"]),
    } for r in items])
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         key="tools", column_config={"Argumen": st.column_config.TextColumn(width="large")})
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        st.caption("Pilih satu baris untuk melihat SQL dan hasilnya.")
        return
    tool_detail(items[rows[0]]["id"])


def tool_detail(run_id: int):
    r = call(f"/tool-runs/{run_id}")
    st.divider()
    st.subheader(f"#{r['id']} · {r['tool']}")
    st.caption(f"{local(r['created_at'])} · {WORKFLOW.get(r['workflow'], r['workflow'])} · "
               f"{KIND.get(r['kind'], r['kind'])} · trace {r['trace_id']}")
    statements = r["statements"] or []
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", STATUS.get(r["status"], r["status"]))
    c2.metric("Latensi", f"{r['latency_ms']} ms")
    c3.metric("Baris", "–" if r["row_count"] is None else r["row_count"])
    c4.metric("Statement SQL", len(statements))
    if r["error"]:
        st.error(r["error"])
    open_trace_button(r["trace_id"])
    t_sql, t_args, t_res, t_ref = st.tabs(["SQL", "Argumen", "Hasil", "Referensi"])
    with t_sql:
        if not statements:
            st.caption("Tidak ada SQL yang tercatat.")
        for n, stmt in enumerate(statements, 1):
            st.markdown(f"**{n}.** {stmt['ms']} ms")
            st.code(stmt["sql"], language="sql", wrap_lines=True)
            if stmt.get("params"):
                st.caption(f"Parameter: {stmt['params']}")
    with t_args:
        st.json(r["args"] or {})
    with t_res:
        result = r["result_preview"]
        if isinstance(result, list) and result and isinstance(result[0], dict):
            st.dataframe(pd.DataFrame(result), hide_index=True, width="stretch")
            if r["row_count"] and r["row_count"] > len(result):
                st.caption(f"Menampilkan {len(result)} dari {r['row_count']} baris.")
        elif result is not None:
            st.json(result)
        else:
            st.caption("Tidak ada hasil tersimpan.")
    with t_ref:
        st.json(r["ref"] or {})


# ------------------------------------------------------------------ agent calls list
@st.fragment(run_every="10s" if auto else None)
def runs_view():
    trace = st.session_state.trace_id
    if trace:
        trace_view(trace)
        return
    if view == "Tool Postgres":
        tools_view()
        return
    data = call("/agent-runs", agent=agents, workflow=workflows, status=statuses, q=q,
                limit=limit, offset=(page - 1) * limit, **period_params())
    items = data["items"]
    st.subheader("Panggilan agent")

    failed = sum(1 for r in items if r["status"] != "ok")
    lat = [r["latency_ms"] for r in items]
    tok = sum((r["input_tokens"] or 0) + (r["output_tokens"] or 0) for r in items)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total (filter)", data["total"])
    c2.metric("Di halaman ini", len(items))
    c3.metric("Gagal / tidak valid", failed)
    c4.metric("Latensi median", f"{int(pd.Series(lat).median())} ms" if lat else "–")
    c5.metric("Token", f"{tok:,}".replace(",", ".") if tok else "–")
    if not items:
        st.info("Tidak ada panggilan untuk filter ini.")
        return

    df = pd.DataFrame([{
        "#": r["id"], "Waktu": local(r["created_at"]), "Agent": r["agent"],
        "Alur": WORKFLOW.get(r["workflow"], r["workflow"]), "Status": STATUS.get(r["status"], r["status"]),
        "Latensi (ms)": r["latency_ms"], "Token": str((r["input_tokens"] or 0) + (r["output_tokens"] or 0) or ""),
        "Ulang": r["retries"], "Trace": r["trace_id"][:8], "Output": preview(r["output"], r["error"]),
    } for r in items])
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key="runs",
                         column_config={"Output": st.column_config.TextColumn(width="large")})
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        st.caption("Pilih satu baris untuk melihat detailnya.")
        return
    detail(items[rows[0]]["id"])


def detail(run_id: int):
    r = call(f"/agent-runs/{run_id}")
    st.divider()
    st.subheader(f"#{r['id']} · {r['agent']}")
    st.caption(f"{local(r['created_at'])} · {WORKFLOW.get(r['workflow'], r['workflow'])} · model {r['model'] or '–'} · "
               f"trace {r['trace_id']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", STATUS.get(r["status"], r["status"]))
    c2.metric("Latensi", f"{r['latency_ms']} ms")
    c3.metric("Token in / out", f"{r['input_tokens'] or '–'} / {r['output_tokens'] or '–'}")
    c4.metric("Percobaan", len(r["attempts"] or []))
    if r["error"]:
        st.error(r["error"])
    open_trace_button(r["trace_id"])
    t_out, t_in, t_sys, t_try, t_ref = st.tabs(["Output", "Input", "System prompt", "Percobaan", "Referensi"])
    with t_out:
        if r["output"] is not None:
            st.json(r["output"])
        else:
            st.caption("Tidak ada output valid.")
    with t_in:
        pretty(r["input"])
    with t_sys:
        st.code(r["system_prompt"] or "", language=None, wrap_lines=True)
    with t_try:
        for n, a in enumerate(r["attempts"] or [], 1):
            st.markdown(f"**Percobaan {n}** · " + ("valid" if not a["errors"] else f"{len(a['errors'])} error skema"))
            for e in a["errors"]:
                st.caption(f"• {e}")
            raw = a["raw"]
            if isinstance(raw, (dict, list)):
                st.json(raw)
            else:
                st.code(str(raw), language=None, wrap_lines=True)
    with t_ref:
        st.json(r["ref"] or {})


runs_view()

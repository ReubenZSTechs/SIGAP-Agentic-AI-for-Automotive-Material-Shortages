"""Agent Hub — browse every LLM agent call (input, prompt, output, retries, latency, tokens).

    pip install -r backend/requirements-streamlit.txt
    streamlit run backend/streamlit_app/agent_hub.py

Talks only to the FastAPI backend (SIGAP_API_URL, default http://localhost:8000/api/v1), which records
each call in `agent_runs` (see docs/AGENT_TRACKING.md). One trace = one chat turn, supplier message,
manager reply or dispatch round; open a trace to follow its agents step by step.
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


# ------------------------------------------------------------------ sidebar
st.session_state.setdefault("trace_id", "")
facets = call("/agent-runs/facets")
with st.sidebar:
    st.title("Agent Hub")
    st.caption(f"Sumber: {API}")
    agents = st.multiselect("Agent", [f["value"] for f in facets["agents"]],
                            format_func=lambda v: f"{v} ({next(f['count'] for f in facets['agents'] if f['value'] == v)})",
                            placeholder="Semua agent")
    workflows = st.multiselect("Alur", [f["value"] for f in facets["workflows"]],
                               format_func=lambda v: WORKFLOW.get(v, v), placeholder="Semua alur")
    statuses = st.multiselect("Status", list(STATUS), format_func=STATUS.get, placeholder="Semua status")
    today = datetime.now(TZ).date()
    period = st.date_input("Periode", (today - timedelta(days=7), today))
    q = st.text_input("Cari di input / output / error", placeholder="mis. Cipta Logam")
    st.session_state.trace_id = st.text_input("Trace id", st.session_state.trace_id).strip()
    limit = st.selectbox("Baris per halaman", [50, 100, 200, 500], index=1)
    page = st.number_input("Halaman", min_value=1, value=1, step=1)
    auto = st.toggle("Muat ulang otomatis (10 dtk)")
    if st.button("Muat ulang", width="stretch"):
        st.rerun()

since, until = (period if isinstance(period, tuple) and len(period) == 2 else (period, period)) if period else (None, None)


# ------------------------------------------------------------------ list
@st.fragment(run_every="10s" if auto else None)
def runs_view():
    trace = st.session_state.trace_id
    data = call("/agent-runs", agent=agents, workflow=workflows, status=statuses, q=q, trace_id=trace,
                since=utc(since) if since and not trace else None, until=utc(until, end=True) if until and not trace else None,
                limit=limit, offset=(page - 1) * limit)
    items = data["items"]

    if trace:
        st.subheader(f"Trace {trace[:12]}…")
        first = items[0] if items else {}
        st.caption(f"{WORKFLOW.get(first.get('workflow'), first.get('workflow', ''))} · ref {first.get('ref') or {}} · "
                   f"{len(items)} panggilan, urut waktu")
        if st.button("Tutup trace"):
            st.session_state.trace_id = ""
            st.rerun()
    else:
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
        "#": n + 1 if trace else r["id"], "Waktu": local(r["created_at"]), "Agent": r["agent"],
        "Alur": WORKFLOW.get(r["workflow"], r["workflow"]), "Status": STATUS.get(r["status"], r["status"]),
        "Latensi (ms)": r["latency_ms"], "Token": str((r["input_tokens"] or 0) + (r["output_tokens"] or 0) or ""),
        "Ulang": r["retries"], "Trace": r["trace_id"][:8], "Output": preview(r["output"], r["error"]),
    } for n, r in enumerate(items)])
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"runs-{trace}",
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
    if not st.session_state.trace_id and st.button("Tampilkan semua panggilan di trace ini", type="primary"):
        st.session_state.trace_id = r["trace_id"]
        st.rerun()
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

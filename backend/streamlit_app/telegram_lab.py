"""Telegram Lab — Streamlit harness for the supplier Telegram agent.

    pip install -r backend/requirements-streamlit.txt
    streamlit run backend/streamlit_app/telegram_lab.py

Talks only to the FastAPI backend (SIGAP_API_URL, default http://localhost:8000/api/v1).
Sandbox mode (TELEGRAM_MODE=sandbox): play the supplier and the manager here.
Telegram mode: link suppliers with the deep link, chat from a phone, and watch the logs here.
"""
import json
import os

import httpx
import streamlit as st

API = os.environ.get("SIGAP_API_URL", "http://localhost:8000/api/v1").rstrip("/")
client = httpx.Client(base_url=API, timeout=180.0)

st.set_page_config(page_title="Telegram Lab · SIGAP", layout="wide")


def call(method: str, path: str, **kw):
    try:
        r = client.request(method, path, **kw)
    except httpx.HTTPError as e:
        st.error(f"Backend tidak dapat dihubungi ({API}): {e}")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        st.error(f"{method} {path} → HTTP {r.status_code}: {detail}")
        return None
    return r.json()


def rupiah(n) -> str:
    return "Rp" + f"{round(n or 0):,}".replace(",", ".")


DIRECTION = {"OUT": ("assistant", "Agent → supplier"), "IN": ("user", "Supplier"),
             "MANAGER_OUT": ("assistant", "Agent → manajer"), "MANAGER_IN": ("user", "Manajer")}


def render_messages(messages: list[dict], show_json: bool, key: str) -> None:
    for m in messages:
        role, who = DIRECTION.get(m["direction"], ("assistant", m["direction"]))
        with st.chat_message(role):
            st.caption(f"{who} · {m['created_at'][:19].replace('T', ' ')}" + (f" · ⚠ {m['error']}" if m.get("error") else ""))
            st.text(m["text"])
            if m.get("buttons") and m["direction"] == "MANAGER_OUT" and status.get("mode") == "sandbox":
                cols = st.columns(len(m["buttons"]))
                for col, b in zip(cols, m["buttons"]):
                    if col.button(b["label"], key=f"{key}-{m['id']}-{b['data']}"):
                        res = call("POST", "/supplier-chat/sandbox/manager", json={"button": b["data"]})
                        if res:
                            st.session_state["last_result"] = res["result"]
                        st.rerun()
            elif m.get("buttons"):
                st.caption("Tombol: " + " · ".join(b["label"] for b in m["buttons"]))
            if show_json and m.get("agent_output"):
                with st.expander("Output agent (JSON)"):
                    st.json(m["agent_output"])


status = call("GET", "/supplier-chat/status") or {}
st.title("Telegram Lab")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Mode", status.get("mode", "?"))
c2.metric("Bot", status.get("bot_username") or "–")
c3.metric("Chat manajer", status.get("manager_chat_id") or "–")
c4.metric("SAP AI Core", "aktif" if status.get("ai_configured") else "belum diisi")
if not status.get("ai_configured"):
    st.warning("AICORE_* belum diisi di backend/.env: agent tidak bisa menyusun/menganalisis pesan (HTTP 503).")

with st.sidebar:
    st.subheader("Kontrol")
    show_json = st.toggle("Tampilkan output agent", value=True)
    if st.button("Jalankan dispatch + timeout"):
        res = call("POST", "/supplier-chat/dispatch")
        if res:
            st.success(f"Dimulai: {res['started'] or '-'} · timeout: {res['timeouts']}")
    if st.button("Muat ulang"):
        st.rerun()
    if st.session_state.get("last_result"):
        st.caption("Hasil aksi terakhir")
        st.json(st.session_state["last_result"])

tab_links, tab_conv, tab_mgr = st.tabs(["1 · Tautan supplier", "2 · Percakapan", "3 · Kotak masuk manajer"])

# ---------------------------------------------------------------- links
with tab_links:
    links = call("GET", "/supplier-chat/links") or []
    st.caption("Supplier harus tertaut sebelum agent dapat mengirim pesan. Sandbox: tautkan dengan satu klik. "
               "Telegram: kirim deep link ke supplier (membuka bot dengan /start <token>).")
    for l in links:
        a, b, c = st.columns([3, 2, 3])
        a.write(f"**{l['supplier_code']}** {l['supplier_name']}")
        b.write("✅ tertaut" if l["linked"] else "— belum tertaut")
        if status.get("mode") == "sandbox":
            if c.button("Tautkan (sandbox)", key=f"link-{l['supplier_id']}", disabled=l["linked"]):
                call("POST", f"/supplier-chat/links/{l['supplier_id']}/sandbox")
                st.rerun()
        elif l.get("deep_link"):
            c.code(l["deep_link"], language=None)
        else:
            c.caption(f"/start {l['link_token']} (isi TELEGRAM_BOT_USERNAME untuk deep link)")

# ---------------------------------------------------------------- conversations
with tab_conv:
    left, right = st.columns([2, 3])
    with left:
        st.subheader("Mulai percakapan")
        pos = call("GET", "/purchase-orders", params={"status": "ISSUED"}) or []
        if pos:
            labels = {f"{p['po_number']} · {p['supplier_name']} · {rupiah(p['total_amount'])}": p["id"] for p in pos}
            choice = st.selectbox("PO ISSUED", list(labels))
            purpose = st.radio("Tujuan", ["CONFIRM_ORDER", "CANCEL_ORDER"], horizontal=True,
                               format_func=lambda p: "Minta konfirmasi" if p == "CONFIRM_ORDER" else "Minta pembatalan")
            if st.button("Kirim ke supplier", type="primary"):
                res = call("POST", "/supplier-chat/conversations", json={"po_id": labels[choice], "purpose": purpose})
                if res:
                    st.session_state["conv_id"] = res["id"]
                    st.rerun()
        else:
            st.info("Belum ada PO ISSUED. Buat lewat Dashboard (\"Buat PO 50 Ban Dalam\") atau halaman Purchase Order.")
        st.subheader("Percakapan")
        convs = call("GET", "/supplier-chat/conversations") or []
        if convs:
            options = {f"#{c['id']} {c['po_number']} · {c['supplier_name']} · {c['purpose']} · {c['status']}": c["id"]
                       for c in convs}
            ids = list(options.values())
            current = st.session_state.get("conv_id")
            idx = ids.index(current) if current in ids else 0
            st.session_state["conv_id"] = options[st.radio("Pilih", list(options), index=idx, label_visibility="collapsed")]
    with right:
        cid = st.session_state.get("conv_id")
        conv = call("GET", f"/supplier-chat/conversations/{cid}") if cid else None
        if conv:
            st.subheader(f"{conv['po_number']} · {conv['supplier_name']}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Status percakapan", conv["status"])
            m2.metric("Konfirmasi PO", (conv.get("confirmation") or {}).get("status", "–"))
            m3.metric("Status PO", conv["po"]["status"] if conv.get("po") else "dihapus")
            render_messages(conv["messages"], show_json, f"c{cid}")
            for cr in conv.get("change_requests", []):
                with st.expander(f"Permintaan revisi #{cr['id']} · {cr['status']}"):
                    st.json({k: cr[k] for k in ("proposed_changes", "invalid_changes", "options", "result")})
            if status.get("mode") == "sandbox":
                text = st.chat_input(f"Balas sebagai {conv['supplier_name']}…")
                if text:
                    with st.spinner("Agent memproses balasan supplier…"):
                        res = call("POST", "/supplier-chat/sandbox/inbound",
                                   json={"supplier_id": conv["supplier_id"], "text": text})
                    if res:
                        st.session_state["last_result"] = res["result"]
                    st.rerun()
            with st.expander("Snapshot PO (JSON)"):
                st.json(conv["po_snapshot"])
        else:
            st.info("Pilih atau mulai percakapan.")

    if status.get("mode") == "sandbox":
        st.divider()
        st.caption("Pesan baru dari supplier tanpa percakapan aktif (mis. minta revisi setelah konfirmasi):")
        sup = {f"{l['supplier_code']} {l['supplier_name']}": l["supplier_id"] for l in links if l["linked"]}
        if sup:
            s1, s2 = st.columns([1, 3])
            who = s1.selectbox("Supplier", list(sup))
            free = s2.text_input("Pesan", key="free-inbound")
            if st.button("Kirim sebagai supplier") and free:
                res = call("POST", "/supplier-chat/sandbox/inbound", json={"supplier_id": sup[who], "text": free})
                if res:
                    st.session_state["last_result"] = res["result"]
                    st.rerun()

# ---------------------------------------------------------------- manager
with tab_mgr:
    crs = call("GET", "/supplier-chat/change-requests") or []
    pending = [c for c in crs if c["status"] in ("PENDING_MANAGER", "AWAITING_MANAGER_CONFIRM")]
    st.subheader(f"Permintaan revisi menunggu keputusan ({len(pending)})")
    for cr in pending:
        with st.container(border=True):
            st.write(f"**#{cr['id']} {cr['po_number']}** · {cr['supplier_name']} · {cr['status']}")
            for ch in cr["proposed_changes"]:
                st.write(f"- {ch['sku']} {ch['name']}: `{ch['field']}` {ch['old']} → **{ch['new']}**")
            for o in cr["options"]:
                extra = ""
                if o["key"] == "approve_change":
                    extra = f" ({rupiah(o['total_before'])} → {rupiah(o['total_after'])})"
                elif o["key"] == "resource":
                    extra = " (" + "; ".join(f"{g['supplier_name']} {rupiah(g['total_amount'])}" for g in o["purchase_orders"]) + ")"
                st.caption(f"• {o['label']}: {o['effect']}{extra}")
    st.subheader("Chat manajer")
    inbox = call("GET", "/supplier-chat/manager-inbox") or {"messages": []}
    render_messages(inbox["messages"], show_json, "mgr")
    if status.get("mode") == "sandbox":
        text = st.text_input("Balas sebagai manajer (teks bebas, mis. \"setujui saja\")", key="mgr-text")
        if st.button("Kirim sebagai manajer") and text:
            with st.spinner("Agent menafsirkan balasan manajer…"):
                res = call("POST", "/supplier-chat/sandbox/manager", json={"text": text})
            if res:
                st.session_state["last_result"] = res["result"]
            st.rerun()
    with st.expander("Semua permintaan revisi (JSON)"):
        st.code(json.dumps(crs, indent=2, ensure_ascii=False), language="json")

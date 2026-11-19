# Supplier Telegram Agent — How It Works

A background agent talks to suppliers on **Telegram** about purchase orders. It keeps the conversation going until it gets a clear answer, then updates the database through tools. It handles four situations:

| Situation | The agent… | When the supplier answers |
|:--|:--|:--|
| A PO was issued (e.g. by [PO automation](AUTOMATION.md)) | asks the supplier to **confirm** the order and its delivery date | confirmed **and every required field given** (delivery date by default) → PO confirmation `CONFIRMED`, version FINAL, final PDF sent |
| A user asked to delete an ISSUED PO | asks the supplier to agree to the **cancellation** | agreed → PO **cancelled** (kept on record as *Dibatalkan*) and on-order released; refused → **manager notified** |
| The supplier asks to **revise** a PO (qty, price, delivery date), during a chat or in a new chat later | sends the manager the options **abort / approve change / re-source** (Telegram buttons **and** the Hub) | manager approves → PO updated, a new PO version is saved, and the supplier gets **only the changes** to confirm; re-source → new PO to another supplier |
| No response, unclear answers, a refusal | sends reminders, then escalates to the manager with the full context | — |

Everything the bot sends to suppliers and to the manager (and the PO PDF) is **always in English**; suppliers may write in Indonesian and the agents understand it. It is mirrored in the frontend **Hub Supplier** (`/supplier-hub`): supplier threads under *Percakapan*, the manager chat under *Chat Manajer*, and revision decisions under *Persetujuan*. A decision taken in Telegram shows up in the Hub, and a decision taken in the Hub removes the stale buttons in Telegram (section 9).

---

## Contents

1. [Architecture](#1-architecture)
2. [Transports: sandbox vs. telegram](#2-transports-sandbox-vs-telegram)
3. [Linking suppliers and the manager](#3-linking-suppliers-and-the-manager)
4. [Conversation lifecycle](#4-conversation-lifecycle)
5. [Revision flow](#5-revision-flow)
6. [Decision mapping](#6-decision-mapping)
6a. [Agent decision limits: dates, prices, cancellations](#6a-agent-decision-limits-dates-prices-cancellations)
6b. [PO missions](#6b-po-missions)
6c. [Guardrail](#6c-guardrail)
7. [Agents](#agents)
8. [Data model](#8-data-model)
9. [Frontend (Hub Supplier) and sync](#9-frontend-hub-supplier-and-sync)
10. [API](#10-api)
11. [Running the worker](#11-running-the-worker)
12. [Configuration](#12-configuration)
13. [Security](#13-security)
14. [Testing](#14-testing)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Architecture

```mermaid
flowchart LR
    subgraph Triggers
      DA[Dashboard PO automation]
      PO[PO page: Terbitkan → ISSUED]
      HUB[Hub Supplier]
    end
    DA -- "queue CONFIRM / CANCEL" --> Q[(supplier_conversations<br/>QUEUED)]
    PO -- "queue CONFIRM" --> Q
    HUB -- "send / cancel, decisions, manager replies" --> S
    W[Worker<br/>app.supplier_chat.worker] -- "dispatch_queued()" --> Q
    W -- "getUpdates long poll" --> TG[(Telegram Bot API)]
    TG -- "supplier / manager messages, button presses" --> W
    W --> S[SupplierChatService]
    S --> RG[supplier_chat_graph<br/>analyze → apply → reply]
    S --> MG[manager_graph<br/>options → decision → execute]
    RG --> T[configs/tools/po_actions.py]
    MG --> T
    T --> DB[(PostgreSQL)]
    S -- "sendMessage (after commit)" --> TG
```

- **`app/supplier_chat/service.py`**: `SupplierChatService` handles links, dispatch (one active conversation per supplier), inbound routing, manager notices, reminders and timeouts.
- **`configs/workflows/supplier_chat_graph.py`**: one supplier reply: `load_context → analyze (LLM) → apply_decision (tools) → escalate | present_revision → deliver`.
- **`configs/workflows/manager_graph.py`**: change-request options, button / free-text decisions, execution.
- **`configs/tools/po_actions.py`**: every DB write. All business rules live here and in `po_service`.
- The DB is the source of truth. The graphs keep no state between messages, so the worker can restart at any time.
- **Messages are sent only after the transaction that produced them commits.** If a write fails, nothing is sent.

## 2. Transports: sandbox vs. telegram

| `TELEGRAM_MODE` | Delivery | Inbound | Use for |
|:--|:--|:--|:--|
| `sandbox` (default) | stored in `supplier_messages` only | Hub: *Simulasi supplier* box in a thread, and *Chat Manajer* (buttons + replies); or `POST /supplier-chat/sandbox/*` | local testing without a bot token |
| `telegram` | Bot API `sendMessage` (inline keyboards for manager options) | worker long-polls `getUpdates` (messages + `callback_query`) | real suppliers |

Both use exactly the same service and workflows. Only `transport.py` differs (`SandboxTransport` / `TelegramTransport`).

## 3. Linking suppliers and the manager

- Each supplier gets a random **link token** (`supplier_telegram_links`). The deep link `https://t.me/<TELEGRAM_BOT_USERNAME>?start=<token>` opens the bot. When the supplier presses *Start*, the bot receives `/start <token>` and maps that chat to the supplier. A token, not the supplier code, is used so nobody can impersonate a supplier by guessing a code.
- One chat maps to one supplier. Re-linking a chat moves it.
- Messages from unknown chats are ignored.
- The **manager** chat comes from `TELEGRAM_MANAGER_CHAT_ID`. In sandbox mode a fixed simulated chat is used. Option buttons are accepted **only** from the manager chat.
- If a conversation is queued for a supplier that has not linked yet, the manager is told once. The conversation starts automatically as soon as the supplier links.

## 4. Conversation lifecycle

```mermaid
stateDiagram-v2
    [*] --> QUEUED : queue_conversation
    QUEUED --> AWAITING_SUPPLIER : dispatch (supplier linked, no other active conversation)
    AWAITING_SUPPLIER --> AWAITING_SUPPLIER : question / unclear (reply)
    AWAITING_SUPPLIER --> CONFIRMED : confirmed (CONFIRM / REVISION_CONFIRM)
    AWAITING_SUPPLIER --> CANCEL_CONFIRMED : confirmed (CANCEL) → PO deleted
    AWAITING_SUPPLIER --> DECLINED : declined → manager notified
    AWAITING_SUPPLIER --> REVISION_REQUESTED : change_requested → manager options
    REVISION_REQUESTED --> CLOSED : manager decided
    AWAITING_SUPPLIER --> ESCALATED : max_turns / no response / PO changed
    REVISION_REQUESTED --> ESCALATED : change request expired / failed
    CONFIRMED --> [*]
    CANCEL_CONFIRMED --> [*]
    DECLINED --> [*]
    CLOSED --> [*]
    ESCALATED --> [*]
```

Purposes: `CONFIRM_ORDER`, `CANCEL_ORDER`, `REVISION_CONFIRM` (an approved revision sent back to the supplier).

**One active conversation per supplier.** A supplier with several POs gets them one after another, so a reply like "ok siap" always refers to exactly one PO. When a conversation closes, the next queued one starts.

Opening messages are written by `supplier_outreach_writer` (greeting + request). Exact figures are always **appended by code**, so the AI never states quantities or prices. The PO is sent **once**:

| Message | Appended by code |
|:--|:--|
| CONFIRM_ORDER opening (first send of a PO) | full PO summary (`po_summary_text`) |
| REVISION_CONFIRM opening | only the approved changes (`revision_diff_text`) + "anything else? otherwise confirm" |
| CANCEL_ORDER opening | PO number; the full summary only if the PO never reached the supplier |
| Reminders, withdrawal notices, Hub missions about a PO | PO number only |
| Final confirmation | the **PDF of the final PO version** (`sendDocument`) |

**Every PO that becomes ISSUED is sent automatically**: from the Dashboard card (automation), from the PO page (*Terbitkan*, `PATCH /purchase-orders/{id}/status`), or as a re-source replacement. `po_actions.ensure_confirm_conversation` never queues a second open conversation for the same PO. The PO detail page can also resend it (*Kirim ke supplier*, e.g. after an escalation) or ask for a cancellation (*Minta pembatalan*).

## 5. Revision flow

```mermaid
sequenceDiagram
    participant S as Supplier
    participant A as Agent
    participant DB as Database (tools)
    participant M as Manager
    S->>A: "Maaf, kami hanya sanggup 40 buah"
    A->>A: supplier_reply_agent → change_requested + proposed_changes
    A->>DB: open_change_request (validate, compute options)
    A-->>S: "Permintaan Anda kami teruskan ke manajer"
    A->>M: briefing + exact diff + buttons [Batalkan PO] [Setujui perubahan] [Pesan ke supplier lain]
    alt Approve change
        M->>A: button cr:<id>:approve_change
        A->>DB: apply_supplier_revision (qty/price/date, totals, stale runs) + po_revisions v(n+1)
        A-->>S: only the changes, "ada perubahan lain?" (REVISION_CONFIRM)
        S->>A: "Oke, tidak ada perubahan lagi"
        A->>DB: confirmation CONFIRMED, current version → FINAL
        A-->>S: PDF of the final PO
    else Abort
        M->>A: button cr:<id>:abort
        A->>DB: delete_po (stock reverted)
        A-->>S: withdrawal notice
    else Re-source
        M->>A: button cr:<id>:resource
        A->>DB: create_and_issue_po (alternative supplier) + delete original
        A-->>S: withdrawal notice
        A-->>A: CONFIRM_ORDER conversation with the new supplier
    end
    A->>M: result (new PO numbers, totals)
```

**The options are computed by tools, never by the LLM** (`open_change_request`):

| Option | Offered when | Effect |
|:--|:--|:--|
| `abort` | always | PO **cancelled** (`CANCELLED`, *Dibatalkan*, kept on record; on-order released, planning runs stale) + withdrawal notice |
| `approve_change` | every requested change maps to a line of this PO and is valid (qty > 0, price ≥ 0, date ≥ PO date); PO still ISSUED with no receipts; revision rounds < `max_revision_rounds` | PO lines updated (new totals shown up front), new PO version saved, supplier gets the list of changes to confirm |
| `resource` | `find_alternative_suppliers()` finds another active supplier for **every** line (same `pick_supplier` policy as PO automation) | new ISSUED PO(s) per alternative supplier (`decided_by = "Manager via Telegram"`), original **cancelled** (kept on record), old supplier notified, new supplier asked to confirm |

- **New chats are picked up.** If a supplier writes while no conversation is open (e.g. a revision after confirming), `supplier_inbound_triage` matches the message to one of their open POs and opens a conversation for it, which then runs the same flow. If the PO is unclear, the agent asks which PO number.
- **Free-text manager replies** (e.g. "setujui saja") go through `manager_decision_agent`. They never run directly: the agent asks for one confirmation button first (`crc:<id>:<choice>` / `crx:<id>`).
- **Stale decisions are refused.** Before writing, the PO is compared with the snapshot taken when the change request was created. If goods were received or the PO changed meanwhile, the request becomes `FAILED`, the manager is told why, and the supplier is unblocked.
- A change request the manager ignores expires after `change_request_ttl_hours`.
- **The PO changes only when the manager approves.** Until then the PO and the frontend show the original values. If any requested change is invalid (e.g. a line that is not on the PO), `approve_change` is not offered; the manager can abort or re-source, or talk to the supplier.
- While a change request waits for the manager, further supplier messages get a "being reviewed" reply. They are still logged and visible in the thread.

### PO versions (`po_revisions`)

| Version | Written when | Status |
|:--|:--|:--|
| v1 | the first CONFIRM_ORDER is dispatched (exactly what the supplier received) | `CURRENT`, later `SUPERSEDED` |
| v2, v3, … | the manager approves a revision (`changes` = the diff, `change_request_id`) | `CURRENT`, later `SUPERSEDED` |
| the latest | the supplier confirms without further changes | `FINAL` + stored PDF (`pdf`, `pdf_message_id`) |

The PO row always holds the latest values; `po_revisions` keeps the history and the final agreed version. The PO detail page shows it under *Riwayat versi PO*, with a PDF per version.

## 6. Decision mapping

`supplier_reply_agent` only classifies (`decision`) and writes `reply_text`. `apply_decision` maps the decision to tools:

| Purpose | `confirmed` | `declined` | `change_requested` | `question` / `unclear` |
|:--|:--|:--|:--|:--|
| CONFIRM_ORDER / REVISION_CONFIRM | required fields complete → promised date checked against the agent's day window (§6a): inside → `record_supplier_confirmation` → CONFIRMED, `finalize_po_revision` → FINAL, final PDF sent; outside → DATE_CHANGE request for the manager. Fields missing → ask for them (no PDF) | `record_supplier_decline` → DECLINED + manager notice | `open_change_request` → price within limit: agent approves; otherwise manager options (if nothing concrete: ask for specifics) | reply, keep waiting; escalate after `max_turns` |
| CANCEL_ORDER | re-check PO (ISSUED, no receipts) → `cancel_po` (CANCELLED, kept) → CANCEL_CONFIRMED | restore previous confirmation → DECLINED + manager asked to call the supplier | treated as refusal | reply, keep waiting; escalate after `max_turns` |

`cancel_requested` (CONFIRM_ORDER / REVISION_CONFIRM) → `handle_supplier_cancellation` (§6a). A `guard_flag` other than `none` → fixed guardrail refusal, nothing changes (§6c).

If the PO is gone or no longer ISSUED/PARTIALLY_RECEIVED when a reply arrives, the conversation closes and the manager is notified (`po_changed`).

### Required confirmation fields

`supplier_chat.required_confirmation_fields` (default `[promised_delivery_date]`; `supplier_reference` can be added) lists what the supplier must give before a PO is final:

- **Partial confirmation.** A confirmation without them (e.g. *"Bisa"*) is remembered: the conversation gets `outcome.confirmed_pending` and `outcome.collected`. The supplier gets a fixed question for exactly what is missing, the confirmation stays `PENDING`, and no PDF is sent.
- **Completing it.** The agent is told `already_confirmed` / `still_needed`. A later message with the missing data (*"Tanggal 24 Oktober"*) completes the confirmation. As a backstop that doesn't rely on the LLM, an unclear reply that still carries the data counts as complete. Then CONFIRMED, FINAL, and one PDF showing *Janji kirim* / *Ref. supplier*.
- **A delivery date is never a revision.** Our needed-by date stays the deadline; any delivery date the supplier gives is their promise. `split_promised_dates` takes every date out of `proposed_changes`, and the date is checked against the agent's window (§6a). Given together with a real revision, it is carried into the REVISION_CONFIRM conversation.

### Messages after the PO is final (triage)

| Triage intent on a CONFIRMED PO | What happens |
|:--|:--|
| `acknowledgement` / `confirmation` (*"Sudah sesuai"*) | fixed thank-you; **no** new conversation, **no** second PDF |
| `delivery_change` with a date | `apply_delivery_date`: inside the window → new FINAL version + PDF, supplier and manager told; outside → DATE_CHANGE request with buttons (§6a) |
| `delivery_change` without a clear date | fixed question asking for the exact date |
| `cancellation_request` | `handle_supplier_cancellation` (§6a) |
| `data_request` | guardrail refusal (§6c) |
| `revision_request` | a CONFIRM_ORDER conversation is reopened and the reply agent extracts the changes |

The triage agent may not claim to have recorded anything. Every confirmation text comes from code, after the write.

## 6a. Agent decision limits: dates, prices, cancellations

The manager sets four limits in *Hub Supplier → Pengaturan → Aturan otonomi → Batas keputusan otomatis agent* (`hub_settings.policies.thresholds`, read by `configs/tools/agent_limits.py`):

| Limit | Default | Meaning |
|:--|--:|:--|
| `delivery_early_days` | 7 | a new delivery date may be up to N days **before** the deadline |
| `delivery_late_days` | 0 | … and up to N days **after** the deadline |
| `price_tolerance_pct` | 10 | a unit price may move by up to ±N % in **either** direction (10 % on Rp100,000 → Rp90,000–110,000 is accepted by the agent) |
| `price_cancel_pct` | 100 | a price change beyond ±N %, or a price ≤ 0, makes no sense: the agent **cancels the PO without the manager** and re-sources (must be larger than the tolerance) |

Settings saved with the old key `price_increase_pct` are read as `price_tolerance_pct`.

The **deadline** of a PO is the earliest needed-by date of its open lines (no needed-by date → any date is accepted).

| Supplier request | Inside the limits (agent decides) | Outside (POChangeRequest for the manager) |
|:--|:--|:--|
| New delivery date (`DATE_CHANGE`) | promised date updated + new FINAL PO version (`revise_promised_date`) + PDF; manager informed | `accept_date` · `reject_date` · `resource` (other supplier that arrives in time) · `abort` |
| Price change (`PRICE_CHANGE`), inside ±tolerance | revision approved by the agent (`cr.result.auto`), REVISION_CONFIRM sent; manager informed | `approve_change` (accept new price) · `negotiate` (manager's counter price per line → sent as a revision) · `resource` (cheaper supplier) · `abort` |
| Price change beyond ±cancel limit or ≤ 0 (`auto_cancel_price`) | PO cancelled at once (only an ISSUED PO without goods receipts; otherwise it is a normal `PRICE_CHANGE`), the supplier is told, then re-sourced exactly like a supplier cancellation | — |
| qty change (`REVISION`) | — always the manager | `abort` · `approve_change` · `resource` |
| Cancellation (`CANCELLATION`) | PO cancelled automatically; replacement via `pick_replacement` (on time = today + lead time ≤ deadline + late days, cheapest first). On time **and** the replacement price within ±tolerance of the cancelled price (cheaper counts too) → new PO issued + PO mission, manager informed | PO already cancelled; `resource` (replacement anyway, with the lateness / price warnings) · `continue_project` (keep the MPS schedules, planning marked stale) · `cancel_project` (cancel the PLANNED schedules that use the material, selectable in the Hub card) |

A cancellation of a PO that already has goods receipts is not executed automatically: the supplier is told the team will follow up and the manager gets an escalation (`supplier_cancel_partial`).

Negotiation from Telegram: press *Ajukan harga nego* (the bot asks for the price) and reply *"nego 12000"* (or per SKU); `manager_decision_agent` reads `counter_prices`, and a confirm button executes it.

## 6b. PO missions

Every PO conversation is tracked as a mission in *Hub Supplier → Misi* (`app/hub/po_missions.py`):

- **Agent → mission.** `queue_conversation` calls `ensure_po_mission` in the same transaction, so every path that contacts a supplier about a PO (dashboard-chat automation, PO approval, replacement POs, the PO page) first creates a `PO_CONFIRM` / `PO_CANCEL` mission; the dispatcher sends the opening afterwards. A REVISION_CONFIRM continues the same mission.
- **Manager → agent.** A manager-created `PO_CONFIRM` / `PO_CANCEL` mission (wizard, *Dari PO*) makes the agent open the PO conversation right away; the conversation attaches to that mission.
- **Progress** is derived from the conversation (`sync`, run by the worker tick and on every mission read): QUEUED → *Antre*, AWAITING_SUPPLIER → *Menunggu balasan*, REVISION_REQUESTED / open request → *Menunggu keputusan manajer*, CONFIRMED / CANCEL_CONFIRMED → mission DONE with a summary, DECLINED / ESCALATED → escalated, PO cancelled or re-sourced → mission closed with the reason. Every transition is written to the activity log.

## 6c. Guardrail

`app/supplier_chat/guardrail.py` protects the agents and the company data:

1. **Rules before any LLM** (`check_inbound`, Indonesian + English) on every supplier message: `data_query` (our stock, other suppliers or their prices, customers, production plans, BOMs, costs, bulk exports, "database"/"query"), `sql_injection`, `prompt_injection` (ignore-instructions, role play, fake `<system>` blocks), `secret_exfiltration` (system prompt, API keys, passwords, chat ids), `authority_claim` ("saya manajer", "manager already approved"), `encoded_payload` (base64/hex/script), `foreign_po` (a PO number that is not this supplier's). The supplier's *own* stock ("stok kami tinggal 20") is allowed.
2. **LLM second layer**: triage intent `data_request` and `guard_flag` on the reply and mission agents go through the same refusal.
3. **Output check** (`check_outbound`): an LLM reply that names another supplier, a PO of another supplier, or a stock figure is replaced with a neutral reply.

Refusals are fixed English texts per category (suppliers may still write Indonesian; detection covers both). Every block is logged (`supplier_messages.agent_output.guardrail`, activity `guardrail_block`); attack-like categories also alert the manager, at most once per supplier per hour.

## Agents

All agents have `configs/agent/<name>.yaml` + `configs/schema/<name>.schema.json` (strict schema, one self-correction retry), registered in `configs/models.yaml`.

| Agent | Output | Notes |
|:--|:--|:--|
| `supplier_outreach_writer` | `message_text`, `language` | opening / revision / withdrawal text **without figures** |
| `supplier_reply_agent` | `decision` (+ `cancel_requested`), `reply_text`, `promised_delivery_date`, `supplier_reference`, `proposed_changes[{material_ref, field, new_value, reason}]`, `change_summary`, `reason`, `guard_flag` | supplier text is passed as untrusted data |
| `supplier_inbound_triage` | `po_number` (from the supplier's open POs only), `intent` (`delivery_change`, `cancellation_request`, `data_request`, …), `reply_text`, `promised_delivery_date`, `reason` | new chats with no active conversation |
| `mission_reply_agent` | `decision`, `items`, `promised_date`, `confidence`, `notes`, `guard_flag` | replies to Hub missions |
| `manager_escalation_writer` | `message_text`, `urgency`, `recommended_option`, `rationale` | the exact details and buttons are appended by code |
| `manager_decision_agent` | `choice`, `change_request_id`, `reply_text`, `counter_prices` | free-text manager replies, always followed by a confirm button |

If `supplier_outreach_writer` or `manager_escalation_writer` fails, a fixed template is used so the message still goes out.

## 8. Data model

`create_all` creates missing tables; new columns on existing tables are added at startup by `app/db_migrate.py` (`ADD COLUMN IF NOT EXISTS`).

| Table | Purpose |
|:--|:--|
| `supplier_telegram_links` | supplier ↔ chat id, `/start` token |
| `supplier_conversations` | one row per PO conversation: purpose, status, `po_snapshot`, `po_id` (SET NULL on delete), turn count, outcome, linked `automation_action_id` |
| `supplier_messages` | every message in/out (supplier & manager), buttons, agent JSON output, delivery errors. In sandbox mode this is the inbox. |
| `po_supplier_confirmations` | per PO: `PENDING`, `CONFIRMED`, `DECLINED`, `CANCEL_PENDING`, `REVISION_PENDING` + promised date, reference, `revision_round` |
| `po_change_requests` | `kind` (REVISION / PRICE_CHANGE / DATE_CHANGE / CANCELLATION), validated changes, invalid changes, options, manager choice, result |
| `po_revisions` | PO versions discussed with the supplier (v1 sent, v2+ approved revisions, FINAL confirmed) with the final PDF |

## 9. Frontend (Hub Supplier) and sync

The Streamlit Telegram Lab was removed; everything runs from the React frontend.

| Need | Where |
|:--|:--|
| Link suppliers (sandbox one click, or deep link + QR) | Hub → *Pengaturan* → *Koneksi Telegram* |
| Send an ISSUED PO / ask for a cancellation | automatic on ISSUED; PO detail → *Kirim ke supplier* / *Minta pembatalan* |
| Bot ↔ supplier messages (incl. the final PDF), take over, sandbox supplier replies | Hub → *Percakapan* → supplier thread |
| Bot ↔ manager messages, option buttons, free-text replies | Hub → *Chat Manajer* |
| Revision / price / date / cancellation options with diff, evidence and impact | Hub → *Persetujuan* |
| Agent limits (date window, price increase) | Hub → *Pengaturan* → *Aturan otonomi* |
| PO conversations as missions | Hub → *Misi* |
| Every manager decision and agent action | *Riwayat Aktivitas* (sidebar) |
| PO versions and the final PDF | PO detail → *Riwayat versi PO* |

**Two-way sync of manager decisions.** Option buttons always run the same `manager_graph` path, whether pressed in Telegram, on a Hub approval card, or in *Chat Manajer*:

- Telegram → Hub: the change request status changes, and the decision is written to the Hub audit log (`decided_by` = `Manager via Telegram`). The Hub pages poll (approvals 15 s, Chat Manajer 5 s, PO detail 15 s).
- Hub → Telegram: the manager's Telegram chat gets "Diputuskan via Hub oleh …", and `close_manager_buttons` removes the option buttons of that change request from the earlier Telegram messages (`editMessageReplyMarkup`). This also happens after a failed or expired request.
- Free-text replies typed in *Chat Manajer* are mirrored to Telegram ("💬 … via Hub") and then interpreted by `manager_decision_agent`, exactly like a Telegram reply (always followed by a confirm button).

A typical sandbox session:

1. Hub → *Pengaturan* → *Koneksi Telegram* → link *SUP-KRT*.
2. Dashboard: *"Buat PO 50 Ban Luar Karet"* → confirm the card. The PO becomes ISSUED, and its thread shows the opening with the full PO summary.
3. In the thread's *Simulasi supplier* box: *"Maaf, kami hanya sanggup 40 buah"*. *Chat Manajer* shows the briefing and three buttons.
4. Press **Setujui perubahan**. The PO detail shows qty 40 and version 2, and the supplier receives only the change.
5. Reply *"Oke, tidak ada perubahan lagi"*. Version 2 becomes FINAL, and the thread shows the PDF sent to the supplier.

## 10. API

Prefix `/api/v1/supplier-chat`:

| Method & path | Purpose |
|:--|:--|
| `GET /status` | mode, bot username, manager chat, AI configured |
| `GET /links` | suppliers with link status, token and deep link |
| `POST /links/{supplier_id}/sandbox` | link a simulated chat (sandbox only) |
| `GET /conversations?status=&po_id=` | list conversations |
| `POST /conversations` `{po_id, purpose: CONFIRM_ORDER\|CANCEL_ORDER}` | queue + dispatch for an ISSUED PO |
| `GET /conversations/{id}` | messages, PO snapshot, current PO, confirmation, change requests |
| `POST /sandbox/inbound` `{supplier_id, text}` | act as the supplier (sandbox only) |
| `POST /sandbox/manager` `{text}` or `{button}` | act as the manager (sandbox only) |
| `GET /manager-inbox` | manager messages |
| `GET /change-requests`, `GET /change-requests/{id}` | change requests with options and results |
| `POST /dispatch` | one worker iteration (dispatch + timeouts) without polling |

Used by the frontend (`/api/v1`):

| Method & path | Purpose |
|:--|:--|
| `GET /hub/manager/messages` | manager chat with button states (`active` / `chosen` / `closed`) |
| `POST /hub/manager/messages` `{text, approver}` | free-text manager reply from the Hub (mirrored to Telegram) |
| `POST /hub/manager/buttons` `{data, approver}` | press an option button (`cr:` / `crc:` / `crx:`) from the Hub |
| `POST /hub/po/{po_id}/supplier-conversation` `{purpose, approver}` | send an ISSUED PO to the supplier, or ask for a cancellation |
| `GET /purchase-orders/{id}/revisions` | PO versions with diffs and status |
| `GET /purchase-orders/{id}/revisions/{rev_id}/pdf` | PDF of a version (the stored final PDF for FINAL) |

Endpoints that run agents return **503** when `AICORE_*` is not configured.

## 11. Running the worker

```bash
cd backend && python -m app.supplier_chat.worker
```

Docker Compose runs it as the `supplier-worker` service. Run **one** worker per bot token, because Telegram allows only one `getUpdates` consumer. The worker:

1. long-polls Telegram (telegram mode) and handles each update,
2. dispatches queued conversations,
3. once a minute, sends reminders, escalates silent conversations and expires ignored change requests.

Without AI Core credentials it waits instead of crash-looping. The Dashboard also triggers a dispatch right after an automation queues work, so in sandbox mode the worker is optional (`POST /dispatch` does the same).

## 12. Configuration

`backend/.env`:

```
TELEGRAM_MODE=sandbox            # or telegram
TELEGRAM_BOT_TOKEN=...           # from @BotFather (telegram mode)
TELEGRAM_BOT_USERNAME=...        # for deep links
TELEGRAM_MANAGER_CHAT_ID=...     # manager's chat id (e.g. from @userinfobot)
```

`backend/configs/models.yaml` → `supplier_chat`:

```yaml
supplier_chat:
  max_turns: 8                 # unclear replies before escalation
  max_revision_rounds: 2       # afterwards only abort / re-source are offered
  reminder_after_hours: 24
  escalate_after_hours: 72
  change_request_ttl_hours: 48
  history_messages: 12
  poll_timeout_s: 25
  idle_sleep_s: 5
  manager_actor: "Manager via Telegram"
  required_confirmation_fields: [promised_delivery_date]   # + supplier_reference
```

## 13. Security

- **Guardrail** (§6c): rule-based checks block data queries, SQL, prompt injection, secret requests and authority claims before any LLM sees the message; LLM `guard_flag` and an output check are further layers.
- **Prompt injection.** Supplier text is passed to the agents as quoted data with explicit instructions to ignore commands inside it. More importantly, the agents cannot pick a PO, a quantity, a price or an action outside their enum: tools take ids from the conversation record and validate every value.
- **Manager-only buttons.** Callback buttons from any chat other than the manager's are ignored. Free-text manager decisions need a confirm button.
- **Link tokens** are random (`secrets.token_urlsafe`). Unknown chats are ignored.
- **Atomic writes, messages after commit.** A re-source either fully happens (new PO + delete) or not at all.
- Keep `TELEGRAM_BOT_TOKEN` only in `backend/.env` (gitignored).

## 14. Testing

Scripted fake LLMs, real test Postgres, sandbox transport:

- `tests/test_supplier_chat.py`:
  - exact PO summary in the opening message
  - confirmation
  - cancellation agreed (PO deleted, on-order reverted, DRAFT runs stale)
  - cancellation refused (manager notified, PO intact)
  - `/start` linking and unknown chats
  - max-turn escalation
  - one active conversation per supplier
  - the sandbox HTTP round trip
- `tests/test_supplier_revision.py`:
  - the three options
  - approve → revised PO → re-confirmation
  - abort
  - re-source to the alternative supplier
  - no re-source option without an alternative
  - new-chat triage
  - free-text manager reply with a confirm button
  - PO changed meanwhile → FAILED
  - supplier buttons ignored
  - PO versions (v1 → v2 → FINAL), diff-only revision message, final PDF
  - Hub ↔ Telegram button sync (`edit_buttons`)
  - `parse_rupiah` price formats

- `tests/test_agent_autonomy.py`:
  - date change inside the window → new FINAL version, PDF, no request; outside → DATE_CHANGE, reject then accept
  - late date in the first confirmation waits for the manager
  - price increase within the limit approved by the agent; above → PRICE_CHANGE with negotiation (counter price sent)
  - supplier cancellation: automatic replacement + PO mission; expensive replacement → manager; no supplier → cancel project
  - PO missions follow the conversation; manager-created PO mission starts the conversation
  - guardrail rules (attacks blocked, normal messages pass), no LLM call on a block, one manager alert per hour, output check
  - activity log filters (agent actions vs manager decisions)

```bash
docker compose exec backend pytest -q tests/test_supplier_chat.py tests/test_supplier_revision.py tests/test_agent_autonomy.py
```

## 15. Troubleshooting

| Symptom | Cause / fix |
|:--|:--|
| Conversation stays `QUEUED` | Supplier not linked (the manager got a notice), or the supplier has another active conversation. Run `POST /dispatch` or check the worker. |
| Manager gets nothing | `TELEGRAM_MANAGER_CHAT_ID` empty (telegram mode). Messages are logged with `error` in `supplier_messages`. |
| `409 getUpdates conflict` in worker logs | Two workers (or another app) poll the same bot. Run only one. |
| 503 from `/supplier-chat/...` | `AICORE_*` not configured. |
| Message logged with `error` | Telegram rejected the send (blocked bot, wrong chat id). See the `error` column. |

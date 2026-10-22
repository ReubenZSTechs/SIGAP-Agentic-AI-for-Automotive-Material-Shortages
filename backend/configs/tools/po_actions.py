"""PO write tools, re-exported in one place for existing callers (`from configs.tools import po_actions as A`).

The code lives in small modules, read them in this order:

    po_common.py               constants, write_session(), PO snapshot & text formatting
    po_sourcing.py             which supplier to order each material from
    po_resolve.py              chat request -> proposal (read-only)
    po_execute.py              confirmed proposal -> po_service calls
    supplier_conversation.py   Telegram conversations with suppliers, PO versions
    supplier_change_request.py supplier revisions and the manager's choice

The LLM never calls these with free parameters: callers pass ids taken from DB records
(automation proposals, conversations, change requests). Business rules live here and in
`po_service` (status machine, stale-run marking); agents only classify and write text.
"""
from app.models import POSupplierConfirmation  # noqa: F401  (dipakai lewat A.POSupplierConfirmation)
from app.models.enums import ConversationPurpose  # noqa: F401
from configs.tools.po_common import (  # noqa: F401
    ACTIVE_CONVERSATION,
    MAX_OPTIONS,
    OPEN_CONVERSATION,
    _iso,
    _unchanged,
    describe_change,
    fmt_qty,
    now,
    po_snapshot,
    po_summary_text,
    revision_diff_text,
    rupiah,
    write_session,
)
from configs.tools.po_execute import cancel_po, confirmation, create_and_issue_po, delete_po, update_draft_po  # noqa: F401
from configs.tools.po_resolve import material_ids, produce_signature, resolve_po_request  # noqa: F401
from configs.tools.po_sourcing import active_links, assign_suppliers, pick_supplier  # noqa: F401
from configs.tools.supplier_change_request import apply_change_request, open_change_request, parse_rupiah  # noqa: F401
from configs.tools.supplier_conversation import (  # noqa: F401
    CONFIRMATION_FIELDS,
    close_conversation,
    collect_confirmation,
    ensure_confirm_conversation,
    finalize_po_revision,
    missing_fields_text,
    note_action,
    queue_conversation,
    record_initial_revision,
    record_supplier_confirmation,
    record_supplier_decline,
    request_po_cancellation,
    revisions,
    split_promised_dates,
    start_supplier_conversation,
    update_promised_date,
    valid_future_date,
)

WRITE_TOOLS = {
    "create_and_issue_po": create_and_issue_po,
    "update_draft_po": update_draft_po,
    "delete_po": delete_po,
    "cancel_po": cancel_po,
    "request_po_cancellation": request_po_cancellation,
    "queue_conversation": queue_conversation,
    "ensure_confirm_conversation": ensure_confirm_conversation,
    "finalize_po_revision": finalize_po_revision,
    "record_supplier_confirmation": record_supplier_confirmation,
    "record_supplier_decline": record_supplier_decline,
    "open_change_request": open_change_request,
    "apply_change_request": apply_change_request,
}

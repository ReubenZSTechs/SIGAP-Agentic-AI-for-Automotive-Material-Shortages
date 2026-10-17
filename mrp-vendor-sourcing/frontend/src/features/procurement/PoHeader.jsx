import Icon from '../../components/common/Icon';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import PoStatusBadge from '../../components/common/PoStatusBadge';
import ApprovalDialog from './ApprovalDialog';
import { purchaseOrderService } from '../../services/purchaseOrderService';
import { toast } from '../../store/toastStore';
import { PO_SOURCE } from '../../utils/constants';
import { formatDate, formatDateTime, formatRupiah } from '../../utils/formatters';

// Workflow bar per (source, status):
//  MANUAL   : DRAFT → [Submit] → PENDING_APPROVAL → [Approve|Reject] → APPROVED → [Terbitkan] → ISSUED ; REJECTED → edit → [Submit ulang]
//  PLANNING : DRAFT → [Terbitkan] → ISSUED (tanpa approval)
export default function PoHeader({ po, onChanged }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [approval, setApproval] = useState(null); // 'approve' | 'reject' | null
  const manual = po.source === 'MANUAL';
  const src = PO_SOURCE[po.source] ?? PO_SOURCE.PLANNING;

  const run = async (fn, okMsg) => {
    setBusy(true);
    try { await fn(); toast.success(okMsg); setConfirmCancel(false); onChanged(); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const issue = () => run(() => purchaseOrderService.setStatus(po.id, 'ISSUED'), 'PO diterbitkan');
  const submit = () => run(() => purchaseOrderService.submit(po.id), 'PO dikirim untuk approval');
  const cancel = () => run(() => purchaseOrderService.setStatus(po.id, 'CANCELLED'), 'PO dibatalkan');

  const edit = <Button variant="secondary" onClick={() => navigate(`/purchase-orders/${po.id}/edit`)}>Edit</Button>;
  const cancelBtn = <Button variant="secondary" className="text-red-600" onClick={() => setConfirmCancel(true)}>Batalkan PO</Button>;
  const actions = {
    DRAFT: manual ? [edit, <Button key="s" loading={busy} onClick={submit}>Submit untuk approval</Button>, cancelBtn]
      : [<Button key="i" loading={busy} onClick={issue}>Terbitkan</Button>, cancelBtn],
    PENDING_APPROVAL: [<Button key="a" onClick={() => setApproval('approve')}>Approve</Button>,
      <Button key="r" variant="danger" onClick={() => setApproval('reject')}>Reject…</Button>, cancelBtn],
    APPROVED: [<Button key="i" loading={busy} onClick={issue}>Terbitkan</Button>, cancelBtn],
    REJECTED: [edit, <Button key="s" loading={busy} onClick={submit}>Submit ulang</Button>, cancelBtn],
    ISSUED: [cancelBtn],
  }[po.status] ?? [];

  return (
    <div className="mb-6 rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-lg font-semibold text-slate-900">{po.po_number}</h1>
            <Badge tone={src.tone}>{src.label}</Badge>
            <PoStatusBadge status={po.status} />
          </div>
          <p className="mt-1 text-sm text-slate-600">
            {po.supplier_name} · Termin {po.payment_term_days > 0 ? `Net ${po.payment_term_days}` : 'tunai'} · Tgl PO {formatDate(po.po_date)}
          </p>
          {po.notes && <p className="mt-1 text-sm text-slate-500">Catatan: {po.notes}</p>}
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Total</div>
          <div className="text-2xl font-bold tracking-tight text-slate-900 tabular-nums">{formatRupiah(po.total_amount)}</div>
        </div>
      </div>

      {manual && (po.submitted_at || po.decided_at) && (
        <ul className="mt-3 space-y-0.5 border-t border-slate-100 pt-3 text-sm text-slate-600">
          {po.submitted_at && <li>Dikirim untuk approval: {formatDateTime(po.submitted_at)}</li>}
          {po.decided_at && po.status !== 'REJECTED' && <li>Disetujui oleh <b>{po.decided_by}</b> · {formatDateTime(po.decided_at)}</li>}
        </ul>
      )}
      {po.status === 'REJECTED' && (
        <p className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
          <Icon name="alert" className="mt-0.5 h-4 w-4" /> <span>Ditolak oleh <b>{po.decided_by}</b>: {po.rejection_reason}</span>
        </p>
      )}

      {actions.length > 0 && <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">{actions.map((a, i) => <span key={a.key ?? i}>{a}</span>)}</div>}

      <ConfirmDialog open={confirmCancel} loading={busy} confirmLabel="Ya, batalkan PO"
        message={`Batalkan ${po.po_number}? Tindakan ini tidak dapat diurungkan.`}
        onConfirm={cancel} onCancel={() => setConfirmCancel(false)} />
      <ApprovalDialog open={!!approval} mode={approval} po={po} onClose={() => setApproval(null)}
        onDone={() => { setApproval(null); onChanged(); }} />
    </div>
  );
}

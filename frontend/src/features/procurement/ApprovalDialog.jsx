import { useEffect, useState } from 'react';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input, { Textarea } from '../../components/common/Input';
import Modal from '../../components/common/Modal';
import { purchaseOrderService } from '../../services/purchaseOrderService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';

const KEY = 'approverName';
const read = () => { try { return localStorage.getItem(KEY) ?? ''; } catch { return ''; } };

// Approval satu tingkat TANPA auth (MVP): nama approver berupa teks, diingat di peramban.
// Jalur upgrade ke RBAC: ganti input nama dengan pengguna login (endpoint tetap).
export default function ApprovalDialog({ open, mode, po, onClose, onDone }) {
  const [name, setName] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const isReject = mode === 'reject';

  useEffect(() => { if (open) { setName(read()); setReason(''); } }, [open]);

  const submit = async () => {
    if (name.trim().length < 2) return toast.error('Nama minimal 2 karakter');
    if (isReject && reason.trim().length < 3) return toast.error('Alasan penolakan wajib diisi (min. 3 karakter)');
    setBusy(true);
    try {
      if (isReject) await purchaseOrderService.reject(po.id, name.trim(), reason.trim());
      else await purchaseOrderService.approve(po.id, name.trim());
      try { localStorage.setItem(KEY, name.trim()); } catch { /* abaikan */ }
      toast.success(isReject ? 'PO ditolak' : 'PO disetujui');
      onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={isReject ? t('Tolak {po}', { po: po?.po_number }) : t('Setujui {po}', { po: po?.po_number })}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button variant={isReject ? 'danger' : 'primary'} loading={busy} onClick={submit}>
            {isReject ? 'Reject' : 'Approve'}
          </Button>
        </>
      )}>
      <div className="space-y-3">
        <FormField label={t('Nama approver')}><Input value={name} onChange={(e) => setName(e.target.value)} /></FormField>
        {isReject && (
          <FormField label={t('Alasan penolakan')}><Textarea value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></FormField>
        )}
      </div>
    </Modal>
  );
}

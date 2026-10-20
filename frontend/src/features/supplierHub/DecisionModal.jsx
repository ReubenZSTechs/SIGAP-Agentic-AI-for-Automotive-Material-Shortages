import { useEffect, useState } from 'react';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input, { Textarea } from '../../components/common/Input';
import Modal from '../../components/common/Modal';

const KEY = 'approverName'; // sama dengan ApprovalDialog PO (MVP tanpa autentikasi)
const read = () => { try { return localStorage.getItem(KEY) ?? ''; } catch { return ''; } };
const COPY = {
  approve: { title: 'Setujui', cta: 'Setujui', variant: 'primary', note: false },
  reject: { title: 'Tolak', cta: 'Tolak', variant: 'danger', note: true, label: 'Alasan penolakan' },
  revision: { title: 'Minta revisi', cta: 'Kirim ke Agent', variant: 'primary', note: true, label: 'Catatan untuk Agent' },
  choose: { title: 'Jalankan opsi', cta: 'Jalankan', variant: 'primary', note: false },
  archive: { title: 'Terima arsip', cta: 'Terima arsip', variant: 'primary', note: false },
  rerequest: { title: 'Minta ulang', cta: 'Kirim ke Agent', variant: 'primary', note: true, label: 'Alasan (diteruskan Agent ke supplier)' },
};

export default function DecisionModal({ open, mode, item, detail, onClose, onSubmit }) {
  const [name, setName] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const c = COPY[mode] ?? COPY.approve;

  useEffect(() => { if (open) { setName(read()); setReason(''); setErr(''); } }, [open]);

  const submit = async () => {
    if (name.trim().length < 2) return setErr('Nama approver minimal 2 karakter');
    if (c.note && reason.trim().length < 3) return setErr(`${c.label} wajib diisi (min. 3 karakter)`);
    setBusy(true);
    try {
      try { localStorage.setItem(KEY, name.trim()); } catch { /* abaikan */ }
      await onSubmit({ approver: name.trim(), reason: reason.trim() });
    } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={`${c.title}: ${item?.title ?? ''}`}
      footer={(<><Button variant="secondary" onClick={onClose}>Batal</Button><Button variant={c.variant} loading={busy} onClick={submit}>{c.cta}</Button></>)}>
      <div className="space-y-3">
        {detail && <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{detail}</p>}
        <FormField label="Nama approver"><Input value={name} onChange={(e) => setName(e.target.value)} /></FormField>
        {c.note && <FormField label={c.label}><Textarea value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></FormField>}
        {err && <p role="alert" className="text-xs font-medium text-red-600">{err}</p>}
      </div>
    </Modal>
  );
}

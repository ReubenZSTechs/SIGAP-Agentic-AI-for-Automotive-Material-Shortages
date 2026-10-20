import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Card from '../../components/common/Card';
import Button from '../../components/common/Button';
import DataTable from '../../components/common/DataTable';
import FormField from '../../components/common/FormField';
import Icon from '../../components/common/Icon';
import Modal from '../../components/common/Modal';
import Tabs from '../../components/common/Tabs';
import Input, { Select } from '../../components/common/Input';
import StateBadge from '../../features/supplierHub/StateBadge';
import DocumentReview from '../../features/supplierHub/document/DocumentReview';
import { DOC_STATUS, DOC_TYPE, shortTime } from '../../features/supplierHub/meta';
import useDisclosure from '../../hooks/useDisclosure';
import useFetch from '../../hooks/useFetch';
import usePolling from '../../hooks/usePolling';
import { hubService } from '../../services/hubService';
import { useHubStore } from '../../store/hubStore';
import { toast } from '../../store/toastStore';

const toBase64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(',')[1]);
  r.onerror = reject;
  r.readAsDataURL(file);
});

// Mode sandbox: unggah file seolah-olah dikirim supplier lewat Telegram.
function SandboxUpload({ open, onClose, onDone }) {
  const suppliers = useFetch(() => (open ? hubService.listSuppliers() : Promise.resolve([])), [open]);
  const [sid, setSid] = useState('');
  const [file, setFile] = useState(null);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);
  const linked = (suppliers.data ?? []).filter((s) => s.telegram === 'CONNECTED' && s.sandbox);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await hubService.sandboxAttachment({ supplier_id: Number(sid), file_name: file.name, mime: file.type || 'application/octet-stream',
        content_base64: await toBase64(file), caption: caption || null });
      toast.success('Dokumen diterima dari supplier (sandbox)');
      onDone(r.documents[0]);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Simulasi kiriman dokumen (sandbox)"
      footer={<><Button variant="secondary" onClick={onClose}>Batal</Button><Button loading={busy} disabled={!sid || !file} onClick={submit}>Kirim sebagai supplier</Button></>}>
      <div className="space-y-3">
        <FormField label="Supplier" hint={linked.length ? null : 'Belum ada supplier yang ditautkan ke chat sandbox (Pengaturan → Koneksi Telegram).'}>
          <Select value={sid} onChange={(e) => setSid(e.target.value)}>
            <option value="">Pilih supplier…</option>
            {linked.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </FormField>
        <FormField label="File (gambar atau PDF, maks. 10 MB)">
          <Input type="file" accept="image/*,application/pdf" className="h-auto py-1.5" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </FormField>
        <FormField label="Keterangan (opsional)"><Input value={caption} onChange={(e) => setCaption(e.target.value)} placeholder="mis. Invoice PO-…" /></FormField>
      </div>
    </Modal>
  );
}

function DocumentIndex() {
  const navigate = useNavigate();
  const telegram = useHubStore((s) => s.telegram);
  const upload = useDisclosure();
  const { data, loading, error, reload } = useFetch(() => hubService.listDocuments(), []);
  const [view, setView] = useState('NEEDS_REVIEW');
  const [type, setType] = useState('');
  usePolling(reload, 15000);

  const rows = useMemo(() => (data ?? []).filter((d) => (view === 'ALL' || d.status === view) && (!type || d.doc_type === type)), [data, view, type]);
  const pending = (data ?? []).filter((d) => d.status === 'NEEDS_REVIEW').length;

  const columns = [
    { key: 'number', header: 'Dokumen', render: (d) => (
      <span className="flex items-center gap-2.5">
        <Icon name={d.kind === 'image' ? 'image' : 'file'} className="h-4 w-4 text-slate-400" />
        <span><span className="block font-mono text-xs font-semibold text-slate-900">{d.number ?? d.file_name}</span>
          <span className="text-xs text-slate-500">{DOC_TYPE[d.doc_type] ?? 'Belum diklasifikasi'}</span></span>
      </span>
    ) },
    { key: 'supplier', header: 'Supplier', render: (d) => d.supplier.name },
    { key: 'po', header: 'PO', className: 'font-mono text-xs', render: (d) => d.po_number ?? '—' },
    { key: 'check', header: 'Pencocokan', render: (d) => (!d.filled
      ? <span className="text-xs text-slate-500">Belum diisi</span>
      : d.mismatches === 0
        ? <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700"><Icon name="check" className="h-3.5 w-3.5" />Semua cocok</span>
        : <span className={`inline-flex items-center gap-1 text-xs font-medium ${d.critical_mismatches ? 'text-red-700' : 'text-amber-700'}`}><Icon name="alert" className="h-3.5 w-3.5" />{d.mismatches} kolom berbeda{d.critical_mismatches ? ' (kunci)' : ''}</span>) },
    { key: 'received', header: 'Diterima', className: 'text-xs text-slate-500 tabular-nums', render: (d) => shortTime(d.received_at) },
    { key: 'status', header: 'Status', render: (d) => <StateBadge meta={DOC_STATUS[d.status]} /> },
  ];

  return (
    <>
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3">
          <Tabs variant="segmented" value={view} onChange={setView}
            tabs={[{ id: 'NEEDS_REVIEW', label: `Perlu validasi (${pending})` }, { id: 'ARCHIVED', label: 'Diarsipkan' }, { id: 'ALL', label: 'Semua' }]} />
          <Select className="ml-auto h-8 w-auto! min-w-0 text-xs" value={type} aria-label="Filter jenis dokumen" onChange={(e) => setType(e.target.value)}>
            <option value="">Semua jenis</option>
            {Object.entries(DOC_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          {telegram?.mode === 'sandbox' && <Button size="sm" variant="secondary" onClick={upload.show}><Icon name="clip" /> Simulasi kiriman</Button>}
        </div>
        {error ? (
          <div className="p-4"><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></div>
        ) : (
          <DataTable columns={columns} rows={rows} loading={loading && !data} onRowClick={(d) => navigate(`/supplier-hub/documents/${d.id}`)}
            emptyText={view === 'NEEDS_REVIEW' ? 'Tidak ada dokumen yang perlu divalidasi. Foto/PDF yang dikirim supplier lewat Telegram muncul di sini.' : 'Belum ada dokumen'} />
        )}
      </Card>
      <SandboxUpload open={upload.open} onClose={upload.hide} onDone={(docId) => { upload.hide(); navigate(`/supplier-hub/documents/${docId}`); }} />
    </>
  );
}

export default function HubDocuments() {
  const { id } = useParams();
  return id ? <DocumentReview key={id} id={id} /> : <DocumentIndex />;
}

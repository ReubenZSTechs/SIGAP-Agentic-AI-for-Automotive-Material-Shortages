import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Badge from '../../../components/common/Badge';
import Button from '../../../components/common/Button';
import Card from '../../../components/common/Card';
import FormField from '../../../components/common/FormField';
import Icon from '../../../components/common/Icon';
import Input, { Select } from '../../../components/common/Input';
import { Spinner } from '../../../components/common/EmptyState';
import StateBadge from '../StateBadge';
import DecisionModal from '../DecisionModal';
import FilePreview from './FilePreview';
import { DOC_STATUS, DOC_TYPE, approverName, dayTime, fmt } from '../meta';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { useHubStore } from '../../../store/hubStore';
import { toast } from '../../../store/toastStore';
import { formatDateTime } from '../../../utils/formatters';

const toForm = (d) => ({
  doc_type: d.doc_type ?? '', number: d.number ?? '', po_id: d.po_id ? String(d.po_id) : '',
  po_number: d.fields.po_number ?? '', doc_date: d.fields.doc_date ?? '', total: d.fields.total ?? '',
  qty: Object.fromEntries(Object.entries(d.fields.qty ?? {}).map(([k, v]) => [k, String(v)])),
});

function Match({ r }) {
  if (r.match == null) return <span className="text-xs text-slate-400">{r.ref == null ? 'Tidak dibandingkan' : 'Belum diisi'}</span>;
  return r.match
    ? <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-700"><Icon name="check" className="h-3.5 w-3.5" /> Cocok</span>
    : <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-700"><Icon name="alert" className="h-3.5 w-3.5" /> Berbeda</span>;
}

// Validasi dokumen tanpa OCR: file asli di kiri, isian admin + perbandingan dengan PO (dihitung server) di kanan.
export default function DocumentReview({ id }) {
  const navigate = useNavigate();
  const refreshStatus = useHubStore((s) => s.refreshStatus);
  const { data: d, error, reload } = useFetch(() => hubService.getDocument(id), [id]);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [ack, setAck] = useState(false);
  const [mode, setMode] = useState(null); // 'archive' | 'rerequest'

  useEffect(() => { if (d) setForm(toForm(d)); }, [d]);
  const dirty = useMemo(() => d && form && JSON.stringify(form) !== JSON.stringify(toForm(d)), [d, form]);

  if (error && !d) return <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></Card>;
  if (!d || !form) return <Spinner />;

  const open = d.status === 'NEEDS_REVIEW';
  const critical = d.compare.filter((r) => r.match === false && r.critical);
  const title = `${DOC_TYPE[d.doc_type] ?? 'Dokumen'} ${d.number ?? d.file_name}`;
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const priced = ['INVOICE', 'TAX_INVOICE'].includes(form.doc_type);

  const save = async () => {
    setSaving(true);
    try {
      await hubService.updateDocument(id, {
        approver: approverName(), doc_type: form.doc_type || null, number: form.number,
        po_id: form.po_id ? Number(form.po_id) : null, po_number: form.po_number || null, doc_date: form.doc_date || null,
        total: priced && form.total !== '' ? Number(form.total) : null,
        qty: Object.fromEntries(Object.entries(form.qty).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])),
      });
      toast.success('Isian disimpan');
      await reload();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };
  const submit = async ({ approver, reason }) => {
    try {
      if (mode === 'archive') await hubService.archiveDocument(id, approver, critical.length > 0 && ack);
      else {
        const r = await hubService.requestDocumentAgain(id, approver, reason);
        if (r.drafted) toast.info('Pesan minta ulang dibuat sebagai draf; kirim dari Percakapan');
      }
      toast.success(mode === 'archive' ? 'Dokumen diarsipkan' : 'Permintaan kirim ulang diteruskan ke supplier');
      setMode(null); reload(); refreshStatus();
    } catch (e) { toast.error(e.message); if (e.status === 409) { setMode(null); reload(); } }
  };

  return (
    <>
      <Button className="mb-3" variant="ghost" size="sm" onClick={() => navigate('/supplier-hub/documents')}><Icon name="arrowLeft" /> Dokumen</Button>
      <div className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="violet">{DOC_TYPE[d.doc_type] ?? 'Belum diklasifikasi'}</Badge>
          <StateBadge meta={DOC_STATUS[d.status]} />
        </div>
        <h2 className="mt-2 text-xl font-bold tracking-tight text-slate-900">{d.number ? <span className="font-mono">{d.number}</span> : d.file_name}</h2>
        <p className="mt-1 text-sm text-slate-500">{d.supplier.name} · diterima {dayTime(d.received_at)} · {d.file_name}</p>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card title="File asli" actions={d.has_file && (
          <a href={hubService.documentFileUrl(d.id)} download={d.file_name} className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline"><Icon name="download" className="h-3.5 w-3.5" /> Unduh</a>
        )}>
          {d.has_file ? <FilePreview url={hubService.documentFileUrl(d.id)} kind={d.kind} name={d.file_name} tall />
            : <p className="py-10 text-center text-sm text-slate-500">{d.note ?? 'File tidak tersimpan.'}</p>}
        </Card>

        <div className="space-y-4">
          <Card title="Isian dari dokumen" actions={<span className="text-xs text-slate-500">diisi manual (tanpa OCR)</span>}>
            <fieldset disabled={!open} className="grid gap-3 sm:grid-cols-2">
              <FormField label="Jenis dokumen">
                <Select value={form.doc_type} onChange={(e) => set({ doc_type: e.target.value })}>
                  <option value="">Pilih…</option>
                  {Object.entries(DOC_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </Select>
              </FormField>
              <FormField label="Nomor dokumen"><Input value={form.number} onChange={(e) => set({ number: e.target.value })} /></FormField>
              <FormField label="PO terkait">
                <Select value={form.po_id} onChange={(e) => set({ po_id: e.target.value, qty: {} })}>
                  <option value="">Pilih PO…</option>
                  {d.po_choices.map((p) => <option key={p.id} value={p.id}>{p.po_number} · {p.status}</option>)}
                </Select>
              </FormField>
              <FormField label="Nomor PO tertulis di dokumen"><Input value={form.po_number} onChange={(e) => set({ po_number: e.target.value })} /></FormField>
              <FormField label="Tanggal dokumen"><Input type="date" value={form.doc_date} onChange={(e) => set({ doc_date: e.target.value })} /></FormField>
              {priced && <FormField label="Total (Rp)"><Input type="number" min="0" value={form.total} onChange={(e) => set({ total: e.target.value })} /></FormField>}
              {d.po && String(d.po.id) === form.po_id && d.po.items.map((it) => (
                <FormField key={it.material_id} label={`Qty ${it.sku} (${it.uom})`}>
                  <Input type="number" min="0" value={form.qty[it.material_id] ?? ''} onChange={(e) => set({ qty: { ...form.qty, [it.material_id]: e.target.value } })} />
                </FormField>
              ))}
            </fieldset>
            {open && (
              <div className="mt-4 flex items-center justify-end gap-2">
                {dirty && <span className="text-xs font-medium text-amber-700">Belum disimpan</span>}
                <Button variant="secondary" loading={saving} disabled={!dirty} onClick={save}>Simpan & bandingkan</Button>
              </div>
            )}
          </Card>

          <Card padded={false} title={`Perbandingan dengan ${d.po_number ?? 'PO'}`}
            actions={<span className="text-xs text-slate-500"><b className={d.mismatches ? 'text-red-700' : ''}>{d.mismatches} berbeda</b></span>}>
            {!d.po_id ? <p className="p-4 text-sm text-slate-500">Pilih PO terkait lalu simpan untuk membandingkan.</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
                      <th className="px-4 py-2 text-left font-medium">Kolom</th>
                      <th className="px-3 py-2 text-right font-medium">Dokumen</th>
                      <th className="px-3 py-2 text-right font-medium">Data PO</th>
                      <th className="px-4 py-2 text-right font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.compare.map((r) => (
                      <tr key={r.key} className={r.match === false && r.critical ? 'bg-red-50/60' : ''}>
                        <td className="px-4 py-2.5"><span className="font-medium text-slate-800">{r.label}</span>{r.critical && <span className="ml-1.5 text-xs text-slate-500">kunci</span>}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{r.doc == null || r.doc === '' ? '—' : fmt(r.doc, r.unit)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-slate-500">{r.ref == null ? '—' : fmt(r.ref, r.unit)}</td>
                        <td className="px-4 py-2.5 text-right"><Match r={r} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Terkait">
            <dl className="space-y-1.5 text-sm">
              {d.po_id && <div className="flex justify-between gap-3"><dt className="text-slate-500">Purchase order</dt><dd><Link className="font-mono text-primary-700 hover:underline" to={`/purchase-orders/${d.po_id}`}>{d.po_number}</Link></dd></div>}
              {d.mission_id && <div className="flex justify-between gap-3"><dt className="text-slate-500">Misi</dt><dd><Link className="font-medium text-primary-700 hover:underline" to={`/supplier-hub/missions/${d.mission_id}`}>Misi #{d.mission_id}</Link></dd></div>}
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Percakapan</dt><dd><Link className="font-medium text-primary-700 hover:underline" to={`/supplier-hub/conversations/${d.thread_id}`}>Buka thread</Link></dd></div>
            </dl>
          </Card>

          <Card>
            {open ? (
              <>
                {critical.length > 0 && (
                  <>
                    <p role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-900">
                      <Icon name="alert" className="mt-0.5 h-4 w-4 text-red-600" />
                      <span>Kolom kunci berbeda: <b>{critical.map((r) => r.label).join(', ')}</b>. Terima arsip dinonaktifkan sampai Anda mengonfirmasi selisihnya.</span>
                    </p>
                    <label className="mb-3 flex items-start gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-primary-600" />
                      Saya sudah mengonfirmasi selisih dengan supplier atau PO dan menerimanya.
                    </label>
                  </>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button variant="secondary" onClick={() => setMode('rerequest')}><Icon name="refresh" /> Minta ulang</Button>
                  <Button disabled={dirty || !d.filled || (critical.length > 0 && !ack)} onClick={() => setMode('archive')}><Icon name="check" /> Terima arsip</Button>
                </div>
                {(!d.filled || dirty) && <p className="mt-2 text-xs text-slate-500">Isi jenis dokumen dan PO terkait, lalu simpan sebelum mengarsipkan.</p>}
              </>
            ) : (
              <p className="text-sm text-slate-500">
                {DOC_STATUS[d.status].label} oleh <b className="text-slate-700">{d.decided_by}</b>, {formatDateTime(d.decided_at)}
                {d.note ? `. Catatan: ${d.note}` : ''}
              </p>
            )}
          </Card>
        </div>
      </div>

      <DecisionModal open={!!mode} mode={mode} item={{ title }} onClose={() => setMode(null)} onSubmit={submit} />
    </>
  );
}

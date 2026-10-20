import { useEffect, useMemo, useState } from 'react';
import Button from '../../../components/common/Button';
import FormField from '../../../components/common/FormField';
import Icon from '../../../components/common/Icon';
import Input, { Select, Textarea } from '../../../components/common/Input';
import Modal from '../../../components/common/Modal';
import Tabs from '../../../components/common/Tabs';
import { Spinner } from '../../../components/common/EmptyState';
import StateBadge from '../StateBadge';
import { AgentTile } from '../thread/MessageBubble';
import { AUTONOMY, SCENARIO, TELEGRAM, approverName } from '../meta';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { COMPANY, formatDeadline, greeting, templateParts } from '../../../utils/template';
import { formatQty, formatRupiah } from '../../../utils/formatters';

const STEPS = ['Sumber & skenario', 'Item & supplier', 'Tenggat & otonomi', 'Pratinjau'];
const pad = (n) => String(n).padStart(2, '0');
const localInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const defaultDeadline = () => { const d = new Date(Date.now() + 2 * 864e5); d.setHours(17, 0, 0, 0); return localInput(d); };
const blank = (poId) => ({ source: poId ? 'PO' : 'MATERIAL', po_id: poId ? String(poId) : '', scenario: '', material_id: '', qty: '',
  item_ids: [], topic: '', supplier_ids: [], deadline: defaultDeadline(), autonomy: '', message: '' });

function Choice({ active, disabled, onClick, children }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} disabled={disabled}
      className={`flex w-full items-start gap-3 rounded-xl border p-3.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        active ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500' : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'}`}>
      {children}
    </button>
  );
}

function SupplierRow({ s, checked, locked, note, onToggle }) {
  return (
    <li>
      <label className={`flex items-center gap-3 px-3 py-2.5 text-sm ${locked ? '' : 'cursor-pointer hover:bg-slate-50'}`}>
        <input type="checkbox" checked={checked} disabled={locked} onChange={onToggle} className="h-4 w-4 rounded border-slate-300 accent-primary-600" />
        <span className="min-w-0 flex-1">
          <span className="font-medium text-slate-800">{s.name}</span>
          <span className="block text-xs text-slate-500">{s.contact}{note ? ` · ${note}` : ''}</span>
        </span>
        {s.telegram !== 'CONNECTED' && <StateBadge meta={TELEGRAM[s.telegram]} />}
      </label>
    </li>
  );
}

// Wizard empat langkah. Sumber misi: material (data master) atau PO yang sudah ada (PO hanya dibaca, tidak diubah).
export default function MissionWizard({ open, poId, onClose, onCreated }) {
  const [step, setStep] = useState(0);
  const [f, setF] = useState(() => blank(poId));
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const base = useFetch(() => (open
    ? Promise.all([hubService.missionOptions(), hubService.getTemplates(), hubService.getPolicies()])
      .then(([options, templates, policies]) => ({ ...options, templates, policies }))
    : Promise.resolve(null)), [open]);
  const po = useFetch(() => (open && f.source === 'PO' && f.po_id ? hubService.poOptions(f.po_id) : Promise.resolve(null)), [open, f.source, f.po_id]);

  useEffect(() => { if (open) { setStep(0); setF(blank(poId)); setErr(''); } }, [open, poId]);
  const set = (patch) => setF((cur) => ({ ...cur, ...patch }));
  const sc = SCENARIO[f.scenario];
  const data = base.data;
  const fromPo = f.source === 'PO';
  const poData = fromPo ? po.data : null;
  const mat = data?.materials.find((m) => String(m.id) === String(f.material_id));
  const suppliersById = useMemo(() => Object.fromEntries((data?.suppliers ?? []).map((s) => [s.id, s])), [data]);

  // Daftar supplier yang ditawarkan di langkah 2.
  const supplierChoices = useMemo(() => {
    if (!data) return [];
    if (fromPo) {
      if (!poData) return [];
      const rows = poData.suppliers.map((s) => ({ s, note: s.role === 'PO' ? 'supplier PO' : `alternatif: ${s.skus.join(', ')}`, role: s.role }));
      return sc?.poOnly || sc?.poSupplierOnly ? rows.filter((r) => r.role === 'PO') : rows;
    }
    const linked = new Map((mat?.suppliers ?? []).map((l) => [l.supplier_id, l]));
    return [...data.suppliers].filter((s) => s.is_active)
      .sort((a, b) => Number(linked.has(b.id)) - Number(linked.has(a.id)) || a.name.localeCompare(b.name))
      .map((s) => {
        const l = linked.get(s.id);
        return { s, note: l ? `harga saat ini ${formatRupiah(l.unit_price)} · ${l.lead_time_days} hari` : null };
      });
  }, [data, fromPo, poData, sc, mat]);

  const chosen = f.supplier_ids.map((id) => suppliersById[id]).filter(Boolean);
  const previewSupplier = chosen.find((s) => String(s.id) === preview) ?? chosen[0];

  const pickScenario = (key) => {
    const s = SCENARIO[key];
    let supplierIds = [];
    if (fromPo && poData) {
      const poSupplier = poData.suppliers.find((x) => x.role === 'PO');
      supplierIds = s.poOnly || s.poSupplierOnly ? [poSupplier.id] : poData.suppliers.map((x) => x.id);
    }
    const outbound = data.policies.scenarios.find((x) => x.key === key)?.outbound ?? 'AUTO';
    set({ scenario: key, supplier_ids: supplierIds, autonomy: outbound, item_ids: poData ? poData.items.map((i) => i.material_id) : [],
      topic: key === 'DOC_REQUEST' && poData ? `invoice dan surat jalan ${poData.po.po_number}` : '' });
  };
  const pickMaterial = (id) => {
    const m = data.materials.find((x) => String(x.id) === id);
    set({ material_id: id, supplier_ids: (m?.suppliers ?? []).map((l) => l.supplier_id) });
  };
  const toggle = (key, id) => set({ [key]: f[key].includes(id) ? f[key].filter((x) => x !== id) : [...f[key], id] });

  const scenarioAllowed = (key) => {
    if (!fromPo) return !SCENARIO[key].poOnly;
    const s = poData?.scenarios.find((x) => x.key === key);
    return !!s?.allowed && !s?.blocked_reason;
  };
  const valid = [
    !!f.scenario && (!fromPo || !!poData) && scenarioAllowed(f.scenario),
    f.supplier_ids.length > 0 && (fromPo
      ? (!sc?.needsItem || f.item_ids.length > 0) && (f.scenario !== 'DOC_REQUEST' || f.topic.trim().length > 2)
      : (sc?.needsItem ? !!f.material_id && Number(f.qty) > 0 : f.topic.trim().length > 2)),
    !!f.deadline && new Date(f.deadline) > new Date(),
    f.message.trim().length > 10,
  ];
  const ERR = ['Pilih sumber dan skenario yang berlaku', 'Lengkapi item/topik dan pilih minimal 1 supplier', 'Tenggat harus di masa depan'];
  const next = () => {
    if (!valid[step]) return setErr(ERR[step]);
    setErr('');
    if (step === 2) set({ message: data.templates.find((t) => t.scenario === f.scenario)?.body ?? '' });
    return setStep(step + 1);
  };
  const submit = async () => {
    if (!valid[3]) return setErr('Pesan terlalu pendek');
    setBusy(true); setErr('');
    try {
      const items = fromPo
        ? (sc.needsItem ? f.item_ids.map((id) => ({ material_id: id })) : [])
        : (sc.needsItem ? [{ material_id: Number(f.material_id), qty: Number(f.qty) }] : []);
      const ms = await hubService.createMission({
        approver: approverName(), scenario: f.scenario, po_id: fromPo ? Number(f.po_id) : null, items,
        topic: f.topic.trim() || null, supplier_ids: f.supplier_ids, deadline: new Date(f.deadline).toISOString(),
        autonomy: f.autonomy || null, message: f.message,
      });
      onCreated(ms);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
    return undefined;
  };

  const itemText = () => {
    if (!sc) return '';
    if (!sc.needsItem) return f.topic || (poData ? poData.po.po_number : '');
    if (fromPo) {
      const its = poData?.items.filter((i) => f.item_ids.includes(i.material_id)) ?? [];
      return its.length === 1 ? `${its[0].name} sebanyak ${formatQty(its[0].qty)} ${its[0].uom}` : 'item-item berikut';
    }
    return mat ? `${mat.name} sebanyak ${f.qty} ${mat.uom}` : '';
  };
  const vars = previewSupplier ? {
    waktu: greeting(), kontak: previewSupplier.contact, supplier: previewSupplier.name, perusahaan: COMPANY, item: itemText(),
    qty: fromPo ? '' : f.qty, satuan: mat?.uom ?? '', po: poData?.po.po_number ?? '', tenggat: f.deadline ? formatDeadline(new Date(f.deadline)) : '',
  } : {};

  return (
    <Modal open={open} onClose={onClose} size="lg" title="Misi baru"
      footer={(
        <>
          {err && <p role="alert" className="mr-auto self-center text-xs font-medium text-red-600">{err}</p>}
          <Button variant="secondary" onClick={step === 0 ? onClose : () => { setErr(''); setStep(step - 1); }}>{step === 0 ? 'Batal' : 'Kembali'}</Button>
          {step < 3 ? <Button onClick={next}>Lanjut</Button> : <Button loading={busy} onClick={submit}><Icon name="send" /> Mulai misi</Button>}
        </>
      )}>
      <ol className="mb-5 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Langkah">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? 'step' : undefined} className={`flex items-center gap-1.5 font-medium ${i === step ? 'text-primary-700' : i < step ? 'text-slate-700' : 'text-slate-400'}`}>
            <span className={`flex h-5 w-5 items-center justify-center rounded-full ${i < step ? 'bg-primary-600 text-white' : i === step ? 'ring-2 ring-primary-600' : 'bg-slate-100'}`}>
              {i < step ? <Icon name="check" className="h-3 w-3" /> : i + 1}
            </span>{s}
          </li>
        ))}
      </ol>

      {base.loading || !data ? (base.error ? <p className="text-sm text-red-600">{base.error.message}</p> : <Spinner />) : (
        <>
          {step === 0 && (
            <div className="space-y-4">
              <Tabs variant="segmented" value={f.source} onChange={(v) => set({ ...blank(), source: v })}
                tabs={[{ id: 'MATERIAL', label: 'Dari material' }, { id: 'PO', label: 'Dari PO' }]} />
              {fromPo && (
                <FormField label="Purchase Order" hint="Item, qty, dan supplier diambil dari PO. PO tidak diubah oleh misi.">
                  <Select value={f.po_id} onChange={(e) => set({ po_id: e.target.value, scenario: '', supplier_ids: [] })}>
                    <option value="">Pilih PO…</option>
                    {data.pos.map((p) => <option key={p.id} value={p.id}>{p.po_number} · {p.supplier_name} · {p.status}</option>)}
                  </Select>
                </FormField>
              )}
              {fromPo && f.po_id && po.loading && <Spinner />}
              {(!fromPo || poData) && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {Object.entries(SCENARIO).map(([k, s]) => {
                    const info = poData?.scenarios.find((x) => x.key === k);
                    const why = !fromPo && s.poOnly ? 'Hanya dari PO' : fromPo && !info?.allowed ? `Tidak berlaku untuk PO ${poData.po.status}` : info?.blocked_reason;
                    return (
                      <Choice key={k} active={f.scenario === k} disabled={!scenarioAllowed(k)} onClick={() => pickScenario(k)}>
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-700"><Icon name={s.icon} className="h-5 w-5" /></span>
                        <span>
                          <span className="block text-sm font-semibold text-slate-900">{s.label}</span>
                          <span className="mt-0.5 block text-xs text-slate-500">{s.desc}</span>
                          {why && <span className="mt-1 block text-xs font-medium text-amber-700">{why}</span>}
                        </span>
                      </Choice>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              {fromPo ? (
                <>
                  {sc.needsItem && (
                    <fieldset>
                      <legend className="mb-1.5 text-sm font-medium text-slate-700">Item dari {poData.po.po_number}</legend>
                      <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                        {poData.items.map((it) => (
                          <li key={it.material_id}>
                            <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-slate-50">
                              <input type="checkbox" checked={f.item_ids.includes(it.material_id)} onChange={() => toggle('item_ids', it.material_id)} className="h-4 w-4 rounded border-slate-300 accent-primary-600" />
                              <span className="font-mono text-xs text-slate-500">{it.sku}</span><span className="flex-1">{it.name}</span>
                              <span className="tabular-nums text-slate-600">{formatQty(it.qty)} {it.uom}</span>
                            </label>
                          </li>
                        ))}
                      </ul>
                    </fieldset>
                  )}
                  {f.scenario === 'DOC_REQUEST' && (
                    <FormField label="Dokumen yang diminta"><Input value={f.topic} onChange={(e) => set({ topic: e.target.value })} /></FormField>
                  )}
                </>
              ) : sc.needsItem ? (
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
                  <FormField label="Material beli">
                    <Select value={f.material_id} onChange={(e) => pickMaterial(e.target.value)}>
                      <option value="">Pilih material…</option>
                      {data.materials.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.sku})</option>)}
                    </Select>
                  </FormField>
                  <FormField label={`Qty${mat ? ` (${mat.uom})` : ''}`}>
                    <Input type="number" min="1" value={f.qty} onChange={(e) => set({ qty: e.target.value })} />
                  </FormField>
                </div>
              ) : (
                <FormField label="Topik / dokumen yang diminta" hint="Dipakai sebagai {item} di template pesan">
                  <Input value={f.topic} placeholder="mis. Faktur pajak Oktober" onChange={(e) => set({ topic: e.target.value })} />
                </FormField>
              )}
              <fieldset>
                <legend className="mb-1.5 text-sm font-medium text-slate-700">Supplier ({f.supplier_ids.length} dipilih)</legend>
                {supplierChoices.length === 0 ? <p className="text-sm text-slate-500">Pilih material dulu.</p> : (
                  <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
                    {supplierChoices.map(({ s, note }) => (
                      <SupplierRow key={s.id} s={s} note={note} checked={f.supplier_ids.includes(s.id)}
                        locked={fromPo && (sc.poOnly || sc.poSupplierOnly)} onToggle={() => toggle('supplier_ids', s.id)} />
                    ))}
                  </ul>
                )}
                <p className="mt-1.5 text-xs text-slate-500">Supplier yang belum terhubung Telegram tetap bisa dipilih; pesannya menunggu sampai supplier terhubung.</p>
              </fieldset>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <FormField label="Tenggat balasan" hint="Lewat tenggat, misi ditutup otomatis dan balasan yang ada dirangkum">
                <Input type="datetime-local" value={f.deadline} min={localInput(new Date())} onChange={(e) => set({ deadline: e.target.value })} className="sm:w-64" />
              </FormField>
              <fieldset>
                <legend className="mb-1.5 text-sm font-medium text-slate-700">Pesan keluar</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  {Object.entries(AUTONOMY).map(([k, a]) => (
                    <Choice key={k} active={f.autonomy === k} onClick={() => set({ autonomy: k })}>
                      <span><span className="block text-sm font-semibold text-slate-900">{a.label}</span><span className="mt-0.5 block text-xs text-slate-500">{a.desc}</span></span>
                    </Choice>
                  ))}
                </div>
              </fieldset>
              <p className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
                <Icon name="shield" className="mt-0.5 h-4 w-4 text-primary-600" />
                Apa pun pilihannya, perubahan harga dan jadwal dari hasil misi tetap masuk Inbox Persetujuan. Misi tidak membuat atau mengubah PO.
              </p>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <FormField label="Template pesan" hint="Variabel dalam {kurung kurawal} diisi per supplier oleh server">
                <Textarea rows={4} value={f.message} onChange={(e) => set({ message: e.target.value })} />
              </FormField>
              <div>
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-700">Pratinjau untuk</span>
                  <Select className="h-8 w-auto! min-w-0 text-xs" value={previewSupplier?.id ?? ''} onChange={(e) => setPreview(e.target.value)} aria-label="Supplier pratinjau">
                    {chosen.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </Select>
                </div>
                <div className="rounded-xl bg-slate-50 p-4">
                  <div className="ml-auto w-fit max-w-[90%]">
                    <div className="mb-1 flex items-center justify-end gap-1.5 text-xs text-slate-500"><AgentTile /> <b className="font-semibold text-slate-700">Agent</b> · template</div>
                    <p className={`whitespace-pre-line rounded-2xl rounded-tr-md px-3.5 py-2.5 text-sm text-slate-800 ${f.autonomy === 'REVIEW' ? 'border border-dashed border-primary-400 bg-primary-50/50' : 'bg-primary-50 ring-1 ring-inset ring-primary-100'}`}>
                      {templateParts(f.message, vars).map((p, i) => (p.key
                        ? <mark key={i} className={`rounded px-0.5 ${p.key.startsWith('!') ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-slate-900'}`}>{p.text}</mark>
                        : <span key={i}>{p.text}</span>))}
                    </p>
                  </div>
                </div>
                <p className="mt-1.5 text-xs text-slate-500">
                  Sorotan kuning = nilai variabel, merah = variabel tidak dikenal. Server menambahkan {fromPo && (sc.poOnly || sc.poSupplierOnly) ? 'ringkasan PO' : 'daftar item (tanpa harga)'} secara otomatis bila relevan.
                </p>
              </div>
              <dl className="grid grid-cols-3 gap-3 rounded-lg border border-slate-200 p-3 text-sm">
                <div><dt className="text-xs text-slate-500">Penerima</dt><dd className="font-medium">{chosen.length} supplier</dd></div>
                <div><dt className="text-xs text-slate-500">Tenggat</dt><dd className="font-medium">{formatDeadline(new Date(f.deadline))}</dd></div>
                <div><dt className="text-xs text-slate-500">Pesan keluar</dt><dd className="font-medium">{AUTONOMY[f.autonomy]?.label}</dd></div>
              </dl>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

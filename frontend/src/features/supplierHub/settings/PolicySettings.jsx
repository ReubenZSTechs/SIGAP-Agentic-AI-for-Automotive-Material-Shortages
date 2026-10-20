import { useEffect, useState } from 'react';
import Button from '../../../components/common/Button';
import Card from '../../../components/common/Card';
import FormField from '../../../components/common/FormField';
import Icon from '../../../components/common/Icon';
import Input from '../../../components/common/Input';
import { Spinner } from '../../../components/common/EmptyState';
import AutonomyMatrix from './AutonomyMatrix';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { toast } from '../../../store/toastStore';
import { approverName } from '../meta';

const DAYS = [[1, 'Sen'], [2, 'Sel'], [3, 'Rab'], [4, 'Kam'], [5, 'Jum'], [6, 'Sab'], [0, 'Min']];
const THRESHOLDS = [
  { key: 'price_change_pct_high', label: 'Perubahan harga dianggap risiko Tinggi di atas', unit: '%' },
  { key: 'delay_days_high', label: 'Keterlambatan dianggap risiko Tinggi di atas', unit: 'hari' },
  { key: 'invoice_tolerance_rp', label: 'Toleransi selisih total invoice', unit: 'Rp' },
  { key: 'reminder_after_hours', label: 'Pengingat misi bila belum dibalas setelah', unit: 'jam' },
  { key: 'escalate_after_hours', label: 'Tandai tanpa balasan setelah', unit: 'jam' },
];

function validate(p) {
  if (p.scenarios.some((s) => s.expiry_hours != null && !(s.expiry_hours >= 1 && s.expiry_hours <= 168))) return 'Batas keputusan harus 1–168 jam';
  if (THRESHOLDS.some((t) => !(p.thresholds[t.key] >= 0) || p.thresholds[t.key] === '')) return 'Semua ambang wajib diisi dengan angka';
  if (p.thresholds.escalate_after_hours <= p.thresholds.reminder_after_hours) return 'Eskalasi harus lebih lama dari pengingat';
  if (p.working_hours.days.length === 0) return 'Pilih minimal satu hari kerja';
  if (p.working_hours.start >= p.working_hours.end) return 'Jam selesai harus setelah jam mulai';
  return '';
}

// Aturan otonomi, ambang eskalasi, dan jam kerja pengiriman. Disimpan sekaligus lewat bilah simpan.
export default function PolicySettings() {
  const { data, loading, error, reload } = useFetch(() => hubService.getPolicies(), []);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const strip = (d) => { const { po_agent: _ignored, ...rest } = d; return rest; };
  useEffect(() => { if (data) setDraft(structuredClone(strip(data))); }, [data]);

  if (error) return <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></Card>;
  if (loading || !draft) return <Spinner />;

  const dirty = JSON.stringify(draft) !== JSON.stringify(strip(data));
  const problem = validate(draft);
  const setTh = (k, v) => setDraft((d) => ({ ...d, thresholds: { ...d.thresholds, [k]: v === '' ? '' : Number(v) } }));
  const setWh = (patch) => setDraft((d) => ({ ...d, working_hours: { ...d.working_hours, ...patch } }));
  const toggleDay = (n) => setWh({ days: draft.working_hours.days.includes(n) ? draft.working_hours.days.filter((x) => x !== n) : [...draft.working_hours.days, n] });
  const save = async () => {
    setBusy(true);
    try { await hubService.savePolicies(draft, approverName()); toast.success('Aturan disimpan'); await reload(); } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 pb-20">
      <Card padded={false} title="Aturan otonomi per skenario">
        <AutonomyMatrix rows={draft.scenarios} onChange={(scenarios) => setDraft((d) => ({ ...d, scenarios }))} />
        <p className="flex items-start gap-2 border-t border-slate-200 px-4 py-3 text-xs text-slate-500">
          <Icon name="info" className="mt-0.5 h-3.5 w-3.5" />
          Otomatis: pesan template langsung dikirim dan tercatat di riwayat. Draf dulu: pesan muncul di thread berlabel belum dikirim. Kartu yang melewati batas keputusan menjadi Kedaluwarsa.
        </p>
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card title="Ambang risiko & eskalasi">
          <div className="space-y-3">
            {THRESHOLDS.map((t) => (
              <div key={t.key} className="flex items-center justify-between gap-3">
                <label htmlFor={t.key} className="text-sm text-slate-700">{t.label}</label>
                <span className="inline-flex shrink-0 items-center gap-1.5">
                  {t.unit === 'Rp' && <span className="text-xs text-slate-500">Rp</span>}
                  <Input id={t.key} type="number" min="0" className={`h-8 text-right ${t.unit === 'Rp' ? 'w-28' : 'w-20'}`} value={draft.thresholds[t.key]} onChange={(e) => setTh(t.key, e.target.value)} />
                  {t.unit !== 'Rp' && <span className="w-7 text-xs text-slate-500">{t.unit}</span>}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-4 flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
            <Icon name="shield" className="mt-0.5 h-4 w-4 text-primary-600" />
            Data berkeyakinan rendah selalu wajib dicek manual, dan kartu risiko Tinggi selalu meminta konfirmasi dampak sebelum disetujui.
          </p>
        </Card>

        <Card title="Jam kerja pengiriman">
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium text-slate-700">Hari</legend>
            <div className="flex flex-wrap gap-1.5">
              {DAYS.map(([n, label]) => {
                const on = draft.working_hours.days.includes(n);
                return (
                  <button key={n} type="button" aria-pressed={on} onClick={() => toggleDay(n)}
                    className={`h-9 w-11 rounded-lg text-sm font-medium ring-1 ring-inset transition-colors ${on ? 'bg-primary-600 text-white ring-primary-600' : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'}`}>{label}</button>
                );
              })}
            </div>
          </fieldset>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <FormField label="Mulai"><Input type="time" value={draft.working_hours.start} onChange={(e) => setWh({ start: e.target.value })} /></FormField>
            <FormField label="Selesai"><Input type="time" value={draft.working_hours.end} onChange={(e) => setWh({ end: e.target.value })} /></FormField>
          </div>
          <p className="mt-1.5 text-xs text-slate-500">Zona waktu WIB (Asia/Jakarta).</p>
          <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={draft.working_hours.queue_outside} onChange={(e) => setWh({ queue_outside: e.target.checked })} className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-primary-600" />
            Antrekan pesan di luar jam kerja dan kirim saat jam kerja berikutnya dimulai
          </label>
        </Card>
      </div>

      <Card title="Agent PO (konfirmasi & revisi PO)">
        <p className="text-sm text-slate-600">Agent PO yang sudah ada tetap memakai pengaturan di <code className="font-mono text-xs">backend/configs/models.yaml</code>; nilainya ditampilkan di sini sebagai referensi.</p>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {[['reminder_after_hours', 'Pengingat', 'jam'], ['escalate_after_hours', 'Eskalasi', 'jam'], ['change_request_ttl_hours', 'Batas opsi revisi', 'jam'],
            ['max_turns', 'Balasan tak jelas maks.', 'kali'], ['max_revision_rounds', 'Putaran revisi maks.', 'kali']].map(([k, label, unit]) => (
            <div key={k}><dt className="text-xs text-slate-500">{label}</dt><dd className="font-semibold tabular-nums text-slate-900">{data.po_agent?.[k] ?? '—'} {unit}</dd></div>
          ))}
        </dl>
      </Card>

      {dirty && (
        <div className="anim-pop sticky bottom-4 z-20 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-lg">
          <span className="flex-1 text-sm text-slate-700">{problem ? <span className="font-medium text-red-600">{problem}</span> : 'Ada perubahan yang belum disimpan.'}</span>
          <Button variant="secondary" onClick={() => setDraft(structuredClone(strip(data)))}>Batalkan</Button>
          <Button loading={busy} disabled={!!problem} onClick={save}>Simpan aturan</Button>
        </div>
      )}
    </div>
  );
}

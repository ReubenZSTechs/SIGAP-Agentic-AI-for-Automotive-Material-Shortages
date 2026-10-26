import { useState } from 'react';
import { Link } from 'react-router-dom';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import Icon from '../../components/common/Icon';
import Input from '../../components/common/Input';
import DiffTable from './DiffTable';
import { CONFIDENCE, DECISION, RISK, delta, isUrgent, timeLeft, typeMeta } from './meta';
import { formatDateTime, formatRupiah } from '../../utils/formatters';
import { t } from '../../i18n';

function Section({ title, children }) {
  return <section className="mt-5"><h3 className="mb-2 text-sm font-semibold text-slate-900">{title}</h3>{children}</section>;
}

// Angka selisih besar untuk jenis yang punya `hero` (mis. keterlambatan).
function Hero({ rows }) {
  const d = delta(rows[0]);
  if (!d) return null;
  return (
    <div className="mt-4 flex items-baseline gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <span className={`text-3xl font-bold tracking-tight tabular-nums ${d.tone}`}>{d.text}</span>
      <span className="text-sm text-slate-600">{rows[0].label.toLowerCase()} bergeser</span>
    </div>
  );
}

// Tautan ke sumber bukti: thread supplier atau misi yang menghasilkan kartu ini.
function ChatLinks({ item }) {
  if (!item.thread_id && !item.mission_id && !item.po_id) return null;
  const cls = 'inline-flex items-center gap-1 text-sm font-medium text-primary-700 hover:underline';
  return (
    <p className="mt-2 flex flex-wrap gap-x-4">
      {item.thread_id && <Link className={cls} to={`/supplier-hub/conversations/${item.thread_id}`}><Icon name="chat" className="h-3.5 w-3.5" /> {t('Buka thread')}</Link>}
      {item.mission_id && <Link className={cls} to={`/supplier-hub/missions/${item.mission_id}`}><Icon name="flag" className="h-3.5 w-3.5" /> {t('Lihat misi')}</Link>}
      {item.po_id && <Link className={cls} to={`/purchase-orders/${item.po_id}`}><Icon name="file" className="h-3.5 w-3.5" /> {t('Buka PO')}</Link>}
    </p>
  );
}

const DANGER = ['abort', 'cancel_project', 'reject_date'];
const PRIMARY = ['approve_change', 'accept_date', 'continue_project'];

// Harga tandingan per baris PO (opsi "Ajukan harga nego").
function CounterPrices({ lines, value, onChange, readOnly }) {
  return (
    <ul className="mt-2 space-y-1.5">
      {lines.map((l) => (
        <li key={l.po_item_id} className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span className="min-w-0 flex-1"><b className="text-slate-800">{l.sku}</b> {l.name} · {t('lama')} {formatRupiah(l.old)} · {t('diminta')} {formatRupiah(l.asked)}</span>
          <span className="inline-flex items-center gap-1">Rp
            <Input type="number" min="0" aria-label={t('Harga nego {sku}', { sku: l.sku })} className="h-8 w-28 text-right" disabled={readOnly}
              value={value[l.po_item_id] ?? ''} onChange={(e) => onChange({ ...value, [l.po_item_id]: e.target.value === '' ? '' : Number(e.target.value) })} />
          </span>
        </li>
      ))}
    </ul>
  );
}

// Jadwal produksi terdampak (opsi lanjutkan / batalkan proyek); pada "Batalkan proyek" bisa dipilih sebagian.
function Schedules({ rows, picked, onToggle, selectable }) {
  return (
    <ul className="mt-2 space-y-1 text-xs text-slate-600">
      {rows.map((s) => (
        <li key={s.id}>
          <label className={`flex items-center gap-2 ${selectable ? 'cursor-pointer' : ''}`}>
            {selectable && <input type="checkbox" checked={picked.has(s.id)} onChange={() => onToggle(s.id)} className="h-3.5 w-3.5 rounded border-slate-300 accent-primary-600" />}
            <span className="font-mono text-slate-800">{s.batch_code}</span> {s.product} · {s.qty} · {s.production_date}
          </label>
        </li>
      ))}
      <li><Link to="/mps" className="font-medium text-primary-700 hover:underline">{t('Periksa di MPS & Planning')}</Link></li>
    </ul>
  );
}

// Opsi dihitung backend (revisi, harga, tanggal kirim, pembatalan), sama dengan tombol Telegram manajer.
function Options({ item, disabled, onChoose }) {
  const pending = item.status === 'PENDING';
  const nego = item.options.find((o) => o.key === 'negotiate');
  const [counter, setCounter] = useState(() => Object.fromEntries((nego?.lines ?? []).map((l) => [l.po_item_id, l.old])));
  const cancelOpt = item.options.find((o) => o.key === 'cancel_project');
  const [picked, setPicked] = useState(() => new Set((cancelOpt?.schedules ?? []).map((s) => s.id)));
  const togglePick = (id) => setPicked((cur) => { const n = new Set(cur); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const counterOk = !nego || nego.lines.every((l) => Number(counter[l.po_item_id]) > 0);

  const choose = (o) => {
    if (o.key === 'negotiate') return onChoose({ ...o, counter_prices: Object.fromEntries(Object.entries(counter).map(([k, v]) => [k, Number(v)])) });
    if (o.key === 'cancel_project') return onChoose({ ...o, schedule_ids: [...picked] });
    return onChoose(o);
  };
  return (
    <ul className="space-y-2">
      {item.options.map((o) => (
        <li key={o.key} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-slate-200 px-3.5 py-3">
          <div className="min-w-0 flex-1 text-sm">
            <p className="font-semibold text-slate-900">{t(o.label)}</p>
            <p className="mt-0.5 text-slate-600">{o.effect}</p>
            {o.total_after != null && (
              <p className="mt-1 text-xs text-slate-500">{t('Total')} <span className="line-through">{formatRupiah(o.total_before)}</span> <b className="text-slate-800">{formatRupiah(o.total_after)}</b></p>
            )}
            {o.purchase_orders.length > 0 && (
              <p className="mt-1 text-xs text-slate-500">PO baru: {o.purchase_orders.map((g) => `${g.supplier_name} ${formatRupiah(g.total_amount)}${g.lead_time_days ? ` · ${g.lead_time_days} hari` : ''}`).join('; ')}</p>
            )}
            {o.warnings?.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-amber-800">{o.warnings.map((w) => <li key={w} className="flex gap-1"><Icon name="alert" className="mt-0.5 h-3 w-3" />{w}</li>)}</ul>
            )}
            {o.key === 'negotiate' && o.lines && <CounterPrices lines={o.lines} value={counter} onChange={setCounter} readOnly={!pending} />}
            {o.schedules?.length > 0 && <Schedules rows={o.schedules} picked={picked} onToggle={togglePick} selectable={pending && o.key === 'cancel_project'} />}
          </div>
          {pending && (
            <Button size="sm" variant={DANGER.includes(o.key) ? 'danger' : PRIMARY.includes(o.key) ? 'primary' : 'secondary'}
              disabled={disabled || (o.key === 'negotiate' && !counterOk) || (o.key === 'cancel_project' && picked.size === 0)}
              onClick={() => choose(o)}>{t('Pilih')}</Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function ApprovalCard({ item, onDecide }) {
  const meta = typeMeta(item.type);
  const rows = item.diff.rows;
  const pending = item.status === 'PENDING';
  const [selected, setSelected] = useState(() => new Set(rows.map((r) => r.key)));
  const [edits, setEdits] = useState({});
  const [ack, setAck] = useState(false);

  const lowConf = item.evidence.some((e) => e.confidence === 'LOW');
  const needAck = item.risk === 'HIGH' || lowConf;
  const count = meta.selectable ? selected.size : rows.length;
  const canApprove = pending && !item.stale && count > 0 && (!needAck || ack);
  const toggle = (k) => setSelected((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const payload = () => ({ version: item.version, selected: [...selected], edits });

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5" aria-label={t(item.title)}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={meta.tone}>{t(meta.label)}</Badge>
        <Badge tone={RISK[item.risk].tone}>Risiko {RISK[item.risk].label.toLowerCase()}</Badge>
        <Badge tone={DECISION[item.status].tone}>{t(DECISION[item.status].label)}</Badge>
      </div>
      <h2 className="mt-3 text-xl font-bold tracking-tight text-slate-900">{t(item.title)}</h2>
      <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-slate-500">
        <span>{item.supplier.name}</span>
        <span>Diajukan Agent {formatDateTime(item.created_at)}</span>
        {pending && (
          <span className={`inline-flex items-center gap-1 ${isUrgent(item) ? 'font-semibold text-amber-700' : ''}`}>
            <Icon name="clock" className="h-3.5 w-3.5" /> Sisa {timeLeft(item.expires_at)}
          </span>
        )}
      </p>
      <p className="mt-3 text-sm text-slate-700">{item.summary}</p>

      {item.stale && pending && (
        <div role="alert" className="mt-4 flex items-start gap-2.5 rounded-lg border border-amber-200 border-l-4 border-l-amber-500 bg-amber-50 px-3.5 py-3 text-sm text-amber-900">
          <Icon name="alert" className="mt-0.5 h-4 w-4 text-amber-600" />
          <span>{meta.options
            ? t('PO berubah sejak permintaan dibuat (mis. sudah ada penerimaan barang), jadi opsi dinonaktifkan. Hubungi supplier secara langsung.')
            : t('Data master berubah sejak diajukan, jadi persetujuan dinonaktifkan. Tolak kartu ini lalu buat misi baru untuk data terbaru.')}</span>
        </div>
      )}
      {item.po_changed && (
        <div role="status" className="mt-4 flex items-start gap-2.5 rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-3 text-sm text-slate-700">
          <Icon name="info" className="mt-0.5 h-4 w-4 text-primary-600" />
          <span>PO berubah sejak misi dibuat. Periksa PO terbaru sebelum memutuskan; isi PO tidak diubah oleh kartu ini.</span>
        </div>
      )}
      {meta.hero && <Hero rows={rows} />}

      <Section title={t('Perubahan')}>
        <DiffTable rows={rows} selectable={!!meta.selectable} readOnly={!pending || item.stale}
          selected={selected} onToggle={toggle} edits={edits} onEdit={(k, v) => setEdits((e) => ({ ...e, [k]: v }))} />
      </Section>

      {item.evidence.length > 0 && (
        <Section title={t('Bukti dari chat ({n})', { n: item.evidence.length })}>
          <ul className="space-y-2">
            {item.evidence.map((e) => (
              <li key={e.id} className="rounded-lg bg-slate-50 px-3.5 py-2.5 text-sm">
                <p className="text-slate-800">{e.excerpt}</p>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
                  <span>{e.from}, {e.at}</span>
                  <span className="inline-flex items-center gap-1.5"><i className={`h-2 w-2 rounded-full ${CONFIDENCE[e.confidence].dot}`} />{t(CONFIDENCE[e.confidence].label)}</span>
                </p>
              </li>
            ))}
          </ul>
          <ChatLinks item={item} />
        </Section>
      )}

      {item.impact.summary && (
        <Section title={t('Dampak')}>
          <p className="text-sm text-slate-700">{item.impact.summary}</p>
          {item.impact.items.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm">
              {item.impact.items.map((i) => (
                <li key={t(i.label)} className="flex flex-wrap items-center gap-x-2 text-slate-600">
                  <span>{t(i.label)}:</span><span className="text-slate-500 line-through">{i.before}</span><b className="text-red-700">{i.after}</b>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {meta.options && (
        <Section title={t('Opsi untuk manajer')}>
          {pending && needAck && !item.stale && (
            <label className="mb-3 flex items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-primary-600" />
              {t('Saya sudah memeriksa dampaknya.')}
            </label>
          )}
          <Options item={item} disabled={item.stale || (needAck && !ack)}
            onChoose={(o) => onDecide('choose', { choice: o.key, label: o.label, counter_prices: o.counter_prices, schedule_ids: o.schedule_ids })} />
        </Section>
      )}

      {pending && meta.options ? null : pending ? (
        <footer className="mt-6 border-t border-slate-200 pt-4">
          {needAck && !item.stale && (
            <label className="mb-3 flex items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-primary-600" />
              {lowConf ? t('Saya sudah memeriksa bukti berkeyakinan rendah secara manual.') : t('Saya sudah memeriksa dampaknya.')}
            </label>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              <Button variant="danger" onClick={() => onDecide('reject', payload())}>{t('Tolak')}</Button>
              <Button variant="secondary" onClick={() => onDecide('revision', payload())}>{t('Minta revisi')}</Button>
            </div>
            <Button disabled={!canApprove} onClick={() => onDecide('approve', payload())}>
              <Icon name="check" /> Setujui{meta.selectable ? ` (${count})` : ''}
            </Button>
          </div>
        </footer>
      ) : (
        <p className="mt-6 border-t border-slate-200 pt-4 text-sm text-slate-500">
          {t(DECISION[item.status].label)}{item.decided_by ? <> oleh <b className="text-slate-700">{item.decided_by}</b></> : ''}{item.decided_at ? `, ${formatDateTime(item.decided_at)}` : ''}
          {item.decision_note ? `. Catatan: ${item.decision_note}` : ''}
        </p>
      )}
    </article>
  );
}

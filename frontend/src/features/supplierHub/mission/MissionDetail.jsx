import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../../../components/common/Button';
import Card from '../../../components/common/Card';
import ConfirmDialog from '../../../components/common/ConfirmDialog';
import DataTable from '../../../components/common/DataTable';
import Icon from '../../../components/common/Icon';
import { Spinner } from '../../../components/common/EmptyState';
import StateBadge from '../StateBadge';
import MissionStepper from './MissionStepper';
import { ScenarioTile } from './MissionList';
import { AUTONOMY, DECISION, MISSION_STATUS, SCENARIO, TARGET_STATE, approverName, dayTime, msLeft, timeLeft } from '../meta';
import useFetch from '../../../hooks/useFetch';
import usePolling from '../../../hooks/usePolling';
import { hubService } from '../../../services/hubService';
import { useHubStore } from '../../../store/hubStore';
import { toast } from '../../../store/toastStore';
import { formatQty } from '../../../utils/formatters';

const WAITING = ['SENT', 'NO_REPLY'];

function Meta({ label, children }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-0.5 text-sm font-medium text-slate-800">{children}</dd></div>;
}

// Progres misi per supplier: sudah berapa yang membalas, siapa yang tertinggal, dan kapan tenggatnya.
export default function MissionDetail({ id }) {
  const navigate = useNavigate();
  const refreshStatus = useHubStore((s) => s.refreshStatus);
  const { data: m, error, reload } = useFetch(() => hubService.getMission(id), [id]);
  const [busy, setBusy] = useState(null);
  const [dialog, setDialog] = useState(null); // 'close' | 'cancel'
  usePolling(reload, 10000);

  const run = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); toast.success(typeof ok === 'function' ? ok(r) : ok); await reload(); refreshStatus(); } catch (e) { toast.error(e.message); } finally { setBusy(null); }
  };

  if (error && !m) return <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></Card>;
  if (!m) return <Spinner />;

  const me = approverName();
  const active = m.status === 'ACTIVE';
  const waiting = m.targets.filter((t) => WAITING.includes(t.state));
  const remindCopy = (r) => (r.drafted ? `${r.count} draf pengingat menunggu review di Percakapan` : `Pengingat dikirim ke ${r.count} supplier`);
  const notLinked = m.targets.filter((t) => t.state === 'QUEUED' && t.supplier.telegram !== 'CONNECTED');

  const columns = [
    { key: 'supplier', header: 'Supplier', render: (t) => (
      <span><span className="block font-medium text-slate-800">{t.supplier.name}</span>
        {t.supplier.telegram !== 'CONNECTED' && t.state === 'QUEUED' && <span className="text-xs text-amber-700">Telegram belum terhubung</span>}</span>
    ) },
    { key: 'state', header: 'Status', render: (t) => (
      <span className="inline-flex flex-wrap items-center gap-1.5"><StateBadge meta={TARGET_STATE[t.state]} />
        {t.draft && <span className="text-xs font-medium text-primary-700">draf menunggu review</span>}
        {t.waiting && <span className="text-xs text-slate-500">{t.waiting}</span>}</span>
    ) },
    { key: 'sent', header: 'Terkirim', className: 'tabular-nums text-slate-600 whitespace-nowrap', render: (t) => (t.sent_at ? dayTime(t.sent_at) : '—') },
    { key: 'replied', header: 'Dibalas', className: 'tabular-nums text-slate-600 whitespace-nowrap', render: (t) => (t.replied_at ? dayTime(t.replied_at) : '—') },
    { key: 'result', header: 'Hasil', render: (t) => (t.result ? <b className="font-semibold tabular-nums text-slate-900">{t.result}</b> : <span className="text-slate-400">—</span>) },
    { key: 'actions', header: 'Aksi', align: 'right', render: (t) => (
      <span className="inline-flex gap-1">
        {active && WAITING.includes(t.state) && (
          <Button size="sm" variant="ghost" loading={busy === `remind-${t.supplier_id}`}
            onClick={() => run(`remind-${t.supplier_id}`, () => hubService.remindMission(id, [t.supplier_id], me), remindCopy)}><Icon name="bell" /> Ingatkan</Button>
        )}
        {active && WAITING.includes(t.state) && (
          <Button size="sm" variant="ghost" className="text-red-700" loading={busy === `esc-${t.supplier_id}`}
            onClick={() => run(`esc-${t.supplier_id}`, () => hubService.escalateTarget(id, t.supplier_id, me), 'Draf eskalasi dibuat dan manajer diberi tahu. Tinjau di Percakapan.')}><Icon name="flag" /> Eskalasi</Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => navigate(`/supplier-hub/conversations/${t.thread_id}`)}>{t.draft ? 'Tinjau draf' : 'Buka'}</Button>
      </span>
    ) },
  ];

  return (
    <>
      <Button className="mb-3" variant="ghost" size="sm" onClick={() => navigate('/supplier-hub/missions')}><Icon name="arrowLeft" /> Misi</Button>

      <Card>
        <div className="flex flex-wrap items-start gap-3">
          <ScenarioTile scenario={m.scenario} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <StateBadge meta={MISSION_STATUS[m.status]} />
              <span className="text-xs text-slate-500">{SCENARIO[m.scenario].label}{m.source === 'PO' ? ' · dari PO' : ''}</span>
            </div>
            <h2 className="mt-1 text-xl font-bold tracking-tight text-slate-900">Misi #{m.number} · {m.title}</h2>
          </div>
          <div className="w-full text-sm sm:w-auto sm:text-right">
            <p className="text-slate-500">Tenggat</p>
            <p className="font-semibold text-slate-900">{dayTime(m.deadline)}</p>
            {active && <p className={`text-xs ${msLeft(m.deadline) < 6 * 3600e3 ? 'font-semibold text-amber-700' : 'text-slate-500'}`}>Sisa {timeLeft(m.deadline)}</p>}
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-slate-200 pt-4 sm:grid-cols-4">
          <Meta label="Item / topik">{m.item}</Meta>
          <Meta label="Pesan keluar">{AUTONOMY[m.autonomy].label}</Meta>
          <Meta label="Dibuat oleh">{m.created_by}</Meta>
          <Meta label={m.po_id ? 'Sumber PO' : 'Dimulai'}>
            {m.po_id ? <Link className="font-mono text-primary-700 hover:underline" to={`/purchase-orders/${m.po_id}`}>{m.po_number}</Link>
              : m.po_number ? <span className="font-mono">{m.po_number} (dihapus)</span> : dayTime(m.created_at)}
          </Meta>
        </dl>
        {m.items.length > 1 && (
          <ul className="mt-3 flex flex-wrap gap-2 text-xs">
            {m.items.map((it) => <li key={it.material_id} className="rounded-md bg-slate-100 px-2 py-1"><span className="font-mono">{it.sku}</span> {it.name} · {formatQty(it.qty)} {it.uom}</li>)}
          </ul>
        )}
        <div className="mt-5"><MissionStepper mission={m} /></div>
      </Card>

      {notLinked.length > 0 && active && (
        <div role="status" className="mt-4 flex flex-wrap items-center gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <Icon name="alert" className="h-4 w-4 text-amber-600" />
          <span className="flex-1">{notLinked.map((t) => t.supplier.name).join(', ')} belum terhubung ke Telegram, jadi pesan belum terkirim.</span>
          <Button size="sm" variant="secondary" onClick={() => navigate('/supplier-hub/settings?tab=telegram')}>Hubungkan</Button>
        </div>
      )}

      {(m.summary || m.approval) && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-primary-100 bg-primary-50 px-4 py-3 text-sm text-primary-900">
          <Icon name="spark" className="h-4 w-4 text-primary-600" />
          <span className="flex-1">{m.summary}</span>
          {m.proposals.map((p) => (
            <Link key={p.id} to={`/supplier-hub?item=${p.id}`} className="inline-flex items-center gap-2 font-semibold text-primary-700 hover:underline">
              {p.title} <StateBadge meta={DECISION[p.status] ?? DECISION.PENDING} />
            </Link>
          ))}
        </div>
      )}

      <Card className="mt-4" padded={false} title={`Supplier (${m.replied}/${m.total} membalas)`}>
        <DataTable columns={columns} rows={m.targets} rowKey="supplier_id" />
        {active && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-4 py-3">
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={waiting.length === 0} loading={busy === 'remind'}
                onClick={() => run('remind', () => hubService.remindMission(id, null, me), remindCopy)}>
                <Icon name="bell" /> Kirim pengingat ke yang belum balas ({waiting.length})
              </Button>
              <Button variant="ghost" className="text-red-600" onClick={() => setDialog('cancel')}>Batalkan misi</Button>
            </div>
            <Button onClick={() => setDialog('close')}>Tutup lebih awal & rangkum</Button>
          </div>
        )}
      </Card>
      <p className="mt-2 text-xs text-slate-500">Pengingat dikirim langsung atau ditahan sebagai draf sesuai aturan otonomi. Eskalasi selalu berupa draf yang perlu Anda review. Misi tidak pernah mengubah PO.</p>

      <ConfirmDialog open={dialog === 'close'} variant="primary" title="Tutup misi lebih awal" confirmLabel="Tutup & rangkum" loading={busy === 'close'}
        message={`${waiting.length + m.targets.filter((t) => ['QUEUED', 'PAUSED'].includes(t.state)).length} supplier yang belum membalas akan ditandai "Tanpa balasan". Agent merangkum ${m.replied} balasan yang sudah masuk lalu mengajukannya ke Inbox Persetujuan.`}
        onCancel={() => setDialog(null)}
        onConfirm={async () => { await run('close', () => hubService.closeMission(id, me), 'Misi ditutup dan dirangkum'); setDialog(null); }} />
      <ConfirmDialog open={dialog === 'cancel'} title="Batalkan misi" confirmLabel="Ya, batalkan" loading={busy === 'cancel'}
        message="Misi dihentikan tanpa ringkasan. Draf yang belum dikirim dibuang. Pesan yang sudah terkirim tidak ditarik."
        onCancel={() => setDialog(null)}
        onConfirm={async () => { await run('cancel', () => hubService.cancelMission(id, me), 'Misi dibatalkan'); setDialog(null); }} />
    </>
  );
}

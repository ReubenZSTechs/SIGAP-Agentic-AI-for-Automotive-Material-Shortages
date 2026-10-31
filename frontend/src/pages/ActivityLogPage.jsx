import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import Badge from '../components/common/Badge';
import Button from '../components/common/Button';
import Card from '../components/common/Card';
import DataTable from '../components/common/DataTable';
import Icon from '../components/common/Icon';
import Input, { Select } from '../components/common/Input';
import Modal from '../components/common/Modal';
import Tabs from '../components/common/Tabs';
import { Spinner } from '../components/common/EmptyState';
import useFetch from '../hooks/useFetch';
import usePolling from '../hooks/usePolling';
import { activityService } from '../services/activityService';
import { formatDateTime } from '../utils/formatters';
import { t } from '../i18n';

const TABS = [
  { id: 'all', label: 'Semua' },
  { id: 'decisions', label: 'Keputusan manajer' },
  { id: 'agent', label: 'Aksi agent' },
];
const ACTOR = { AGENT: { label: 'Agent', tone: 'indigo' }, MANAGER: { label: 'Manajer', tone: 'green' }, SYSTEM: { label: 'Sistem', tone: 'slate' } };
const TONE = { guardrail_block: 'red', guardrail_alert: 'red', supplier_cancelled: 'amber', escalate_date: 'amber',
  escalate_change: 'amber', escalate_cancellation: 'amber', supplier_cancel_partial: 'amber', auto_accept_date: 'green',
  auto_accept_price: 'green', replacement_po: 'violet', po_confirmed: 'green', po_declined: 'red' };
const PAGE = 50;
const blank = { action: '', supplier_id: '', po_number: '', q: '', since: '', until: '' };

// Tautan ke objek yang disentuh aktivitas (PO, misi, ajuan, thread supplier).
function RefLink({ row }) {
  const cls = 'font-medium text-primary-700 hover:underline';
  if (row.ref_type === 'change_request') return <Link className={cls} to={`/supplier-hub?item=cr-${row.ref_id}`}>{t('Ajuan')} cr-{row.ref_id}</Link>;
  if (row.ref_type === 'proposal') return <Link className={cls} to={`/supplier-hub?item=hp-${row.ref_id}`}>{t('Ajuan')} hp-{row.ref_id}</Link>;
  if (row.ref_type === 'mission') return <Link className={cls} to={`/supplier-hub/missions/${row.ref_id}`}>{t('Misi #{n}', { n: row.ref_id })}</Link>;
  if (row.po_id) return <Link className={`${cls} font-mono`} to={`/purchase-orders/${row.po_id}`}>{row.po_number}</Link>;
  if (row.po_number) return <span className="font-mono">{row.po_number}</span>;
  if (row.ref_type === 'supplier' && row.supplier?.id) return <Link className={cls} to={`/supplier-hub/conversations/${row.supplier.id}`}>{t('Thread')}</Link>;
  return <span className="text-slate-400">{row.ref_type} #{row.ref_id}</span>;
}

function Detail({ id, onClose }) {
  const { data, loading, error } = useFetch(() => (id ? activityService.get(id) : Promise.resolve(null)), [id]);
  return (
    <Modal open={!!id} onClose={onClose} size="lg" title={data ? `${t(data.action_label)} · #${data.id}` : t('Aktivitas')}>
      {loading || !data ? (error ? <p className="text-sm text-red-600">{error.message}</p> : <Spinner />) : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={ACTOR[data.actor_type]?.tone}>{t(ACTOR[data.actor_type]?.label ?? data.actor_type)}</Badge>
            <span className="font-medium text-slate-800">{data.actor}</span>
            <span className="text-slate-500">{formatDateTime(data.at)}</span>
          </div>
          <p className="text-slate-800">{data.summary}</p>
          <dl className="grid grid-cols-2 gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-4">
            <div><dt className="text-xs text-slate-500">{t('Objek')}</dt><dd><RefLink row={data} /></dd></div>
            <div><dt className="text-xs text-slate-500">{t('Supplier')}</dt><dd>{data.supplier?.name ?? '—'}</dd></div>
            <div><dt className="text-xs text-slate-500">{t('Aksi')}</dt><dd className="font-mono text-xs">{data.action}</dd></div>
            <div><dt className="text-xs text-slate-500">Trace</dt><dd className="truncate font-mono text-xs">{data.trace_id ?? '—'}</dd></div>
          </dl>
          {data.agent_runs.length > 0 && (
            <section>
              <h3 className="mb-1.5 font-semibold text-slate-900">{t('Panggilan LLM pada alur yang sama ({n})', { n: data.agent_runs.length })}</h3>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                {data.agent_runs.map((r) => (
                  <li key={r.id} className="px-3 py-2">
                    <p className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-semibold">{r.agent}</span>
                      <Badge tone={r.status === 'ok' ? 'green' : 'red'}>{r.status}</Badge>
                      <span className="text-xs text-slate-500">{r.latency_ms} ms</span></p>
                    {r.output && <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">{JSON.stringify(r.output, null, 2)}</pre>}
                    {r.error && <p className="mt-1 text-xs text-red-600">{r.error}</p>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {data.tool_runs.length > 0 && (
            <section>
              <h3 className="mb-1.5 font-semibold text-slate-900">{t('Tool database ({n})', { n: data.tool_runs.length })}</h3>
              <ul className="flex flex-wrap gap-2">{data.tool_runs.map((r) => <li key={r.id}><Badge tone={r.status === 'ok' ? 'slate' : 'red'}>{r.tool} · {r.kind}</Badge></li>)}</ul>
            </section>
          )}
          {Object.keys(data.detail ?? {}).length > 0 && (
            <section>
              <h3 className="mb-1.5 font-semibold text-slate-900">{t('Detail')}</h3>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(data.detail, null, 2)}</pre>
            </section>
          )}
        </div>
      )}
    </Modal>
  );
}

// Observabilitas agent: setiap keputusan manajer dan setiap tindakan agent (otomatis, eskalasi, guardrail).
export default function ActivityLogPage() {
  const [tab, setTab] = useState('all');
  const [f, setF] = useState(blank);
  const [applied, setApplied] = useState(blank);
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState({ total: 0, next: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const facets = useFetch(() => activityService.facets(), []);

  const params = useMemo(() => ({
    ...(tab === 'decisions' ? { decisions: true } : tab === 'agent' ? { actor_type: ['AGENT'] } : {}),
    ...(applied.action ? { action: [applied.action] } : {}),
    ...(applied.supplier_id ? { supplier_id: applied.supplier_id } : {}),
    ...(applied.po_number ? { po_number: applied.po_number } : {}),
    ...(applied.q ? { q: applied.q } : {}),
    ...(applied.since ? { since: `${applied.since}T00:00:00` } : {}),
    ...(applied.until ? { until: `${applied.until}T23:59:59` } : {}),
    limit: PAGE,
  }), [tab, applied]);

  const load = useCallback(async (more = false, silent = false) => {   // silent: polling tanpa mengosongkan tabel
    if (!more && !silent) setLoading(true);
    try {
      const r = await activityService.list(more && meta.next ? { ...params, before_id: meta.next } : params);
      setRows((cur) => (more ? [...cur, ...r.items] : r.items));
      setMeta({ total: r.total, next: r.next_before_id });
      setError(null);
    } catch (e) { setError(e); } finally { setLoading(false); }
  }, [params, meta.next]);

  useEffect(() => { load(false); }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  usePolling(() => { if (!meta.next || rows.length <= PAGE) load(false, true); }, 20000);

  const counts = Object.fromEntries((facets.data?.actor_types ?? []).map((a) => [a.value, a.count]));
  const tabs = TABS.map((x) => ({ ...x, label: x.id === 'agent' && counts.AGENT ? `${t(x.label)} (${counts.AGENT})` : x.label }));
  const set = (patch) => setF((cur) => ({ ...cur, ...patch }));
  const apply = () => setApplied(f);
  const reset = () => { setF(blank); setApplied(blank); };

  const columns = [
    { key: 'at', header: 'Waktu', className: 'whitespace-nowrap tabular-nums text-slate-600', render: (r) => formatDateTime(r.at) },
    { key: 'actor', header: 'Pelaku', render: (r) => (
      <span className="inline-flex flex-col gap-0.5"><Badge tone={ACTOR[r.actor_type]?.tone}>{t(ACTOR[r.actor_type]?.label ?? r.actor_type)}</Badge>
        {r.actor_type !== 'AGENT' && <span className="text-xs text-slate-500">{r.actor}</span>}</span>
    ) },
    { key: 'action', header: 'Aksi', render: (r) => <Badge tone={TONE[r.action] ?? (r.is_decision ? 'green' : 'slate')}>{t(r.action_label)}</Badge> },
    { key: 'summary', header: 'Ringkasan', render: (r) => <span className="line-clamp-2 text-slate-800">{r.summary}</span> },
    { key: 'supplier', header: 'Supplier', className: 'whitespace-nowrap text-slate-600', render: (r) => r.supplier?.name ?? '—' },
    { key: 'ref', header: 'Objek', className: 'whitespace-nowrap', render: (r) => <span onClick={(e) => e.stopPropagation()}><RefLink row={r} /></span> },
  ];

  return (
    <>
      <PageHeader title={t('Riwayat Aktivitas')}
        subtitle={t('Jejak keputusan manajer dan setiap tindakan agent (otomatis, eskalasi ke manajer, guardrail) untuk observabilitas.')}
        actions={<Button variant="secondary" onClick={() => load(false)}><Icon name="refresh" /> {t('Muat ulang')}</Button>} />

      <div className="-mx-4 mb-4 overflow-x-auto px-4 sm:mx-0 sm:px-0"><Tabs tabs={tabs} value={tab} onChange={setTab} /></div>

      <Card className="mb-4">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6" onSubmit={(e) => { e.preventDefault(); apply(); }}>
          <Input className="lg:col-span-2" placeholder={t('Cari ringkasan, pelaku, atau detail…')} aria-label={t('Cari')} value={f.q} onChange={(e) => set({ q: e.target.value })} />
          <Select aria-label={t('Aksi')} value={f.action} onChange={(e) => set({ action: e.target.value })}>
            <option value="">{t('Semua aksi')}</option>
            {(facets.data?.actions ?? []).map((a) => <option key={a.value} value={a.value}>{t(a.label)} ({a.count})</option>)}
          </Select>
          <Select aria-label={t('Supplier')} value={f.supplier_id} onChange={(e) => set({ supplier_id: e.target.value })}>
            <option value="">{t('Semua supplier')}</option>
            {(facets.data?.suppliers ?? []).map((s) => <option key={s.value} value={s.value}>{s.label} ({s.count})</option>)}
          </Select>
          <Input placeholder={t('No. PO')} aria-label={t('No. PO')} value={f.po_number} onChange={(e) => set({ po_number: e.target.value })} />
          <div className="flex gap-2">
            <Button type="submit" className="flex-1"><Icon name="filter" /> {t('Terapkan')}</Button>
            <Button type="button" variant="ghost" onClick={reset} aria-label={t('Reset filter')}><Icon name="x" /></Button>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-500 lg:col-span-2">{t('Dari')}
            <Input type="date" value={f.since} onChange={(e) => set({ since: e.target.value })} /></label>
          <label className="flex items-center gap-2 text-xs text-slate-500 lg:col-span-2">{t('Sampai')}
            <Input type="date" value={f.until} onChange={(e) => set({ until: e.target.value })} /></label>
        </form>
      </Card>

      <Card padded={false} title={t('{n} aktivitas', { n: meta.total })}>
        {error ? <p className="px-4 py-6 text-sm text-red-600">{error.message}</p> : (
          <DataTable columns={columns} rows={rows} loading={loading} onRowClick={(r) => setOpen(r.id)}
            emptyText="Belum ada aktivitas yang cocok dengan filter." />
        )}
        {meta.next && !loading && (
          <div className="border-t border-slate-200 px-4 py-3 text-center">
            <Button variant="secondary" onClick={() => load(true)}>{t('Muat lebih banyak')} ({rows.length}/{meta.total})</Button>
          </div>
        )}
      </Card>
      <Detail id={open} onClose={() => setOpen(null)} />
    </>
  );
}

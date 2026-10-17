import Icon from '../components/common/Icon';
import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Tabs from '../components/common/Tabs';
import { Select } from '../components/common/Input';
import { Spinner } from '../components/common/EmptyState';
import ScheduleTable from '../features/mps/ScheduleTable';
import ScheduleFormModal from '../features/mps/ScheduleFormModal';
import ScheduleDrawer from '../features/mps/ScheduleDrawer';
import StaleRunBanner from '../features/mps/StaleRunBanner';
import RunPlanningPanel from '../features/mps/RunPlanningPanel';
import PlanningRunList from '../features/mps/PlanningRunList';
import useFetch from '../hooks/useFetch';
import { scheduleService } from '../services/scheduleService';
import { planningService } from '../services/planningService';
import { useMasterStore } from '../store/masterStore';

// FullCalendar (+68 KB gzip) hanya diunduh saat tampilan Kalender dibuka.
const ScheduleCalendar = lazy(() => import('../features/mps/ScheduleCalendar'));

// Kalender & tabel = dua tampilan atas satu sumber data (`GET /schedules`). Default: Kalender.
export default function MpsPage() {
  const { ensureLoaded } = useMasterStore();
  const [params, setParams] = useSearchParams();
  const view = params.get('view') === 'table' ? 'table' : 'calendar';
  const [form, setForm] = useState({ open: false, schedule: null });
  const [selectedId, setSelectedId] = useState(null);
  const [showCancelled, setShowCancelled] = useState(false);
  const [lineId, setLineId] = useState('');
  const [prefill, setPrefill] = useState(null);
  const panelRef = useRef(null);
  const { lines } = useMasterStore();
  useEffect(() => { ensureLoaded(true); }, [ensureLoaded]);

  const schedules = useFetch(() => scheduleService.list(), []);
  const runs = useFetch(() => planningService.listRuns(), []);
  const reloadAll = () => Promise.all([schedules.reload(), runs.reload()]);

  const latestRun = runs.data?.[0]; // daftar run terurut terbaru -> lama
  const staleRuns = latestRun?.is_stale ? [latestRun] : [];
  const selected = schedules.data?.find((s) => s.id === selectedId) ?? null;

  const setView = (v) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (v === 'table') next.set('view', 'table'); else next.delete('view');
    return next;
  }, { replace: true });

  const rerun = (run) => {
    setPrefill({ date_from: run.date_from, date_to: run.date_to, k: Date.now() });
    panelRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  };

  return (
    <>
      <PageHeader title="MPS & Stock Planning" subtitle="Jadwal produksi, status stok, lalu planning"
        actions={(
          <>
            <Tabs variant="segmented" value={view} onChange={setView}
                  tabs={[{ id: 'table', label: 'Tabel' }, { id: 'calendar', label: 'Kalender' }]} />
            <Button onClick={() => setForm({ open: true, schedule: null })}><Icon name="plus" /> Tambah Jadwal</Button>
          </>
        )} />
      <StaleRunBanner run={latestRun} onRerun={rerun} />

      <div className="space-y-5">
        <Card title={view === 'calendar' ? 'Kalender Produksi' : 'Jadwal Produksi'} padded={view === 'calendar'}
          actions={view === 'calendar' ? (
            <>
              <Select className="w-36 py-1 text-xs" aria-label="Filter line" value={lineId} onChange={(e) => setLineId(e.target.value)}>
                <option value="">Line: Semua</option>
                {lines.map((l) => <option key={l.id} value={l.id}>{l.code}</option>)}
              </Select>
              <label className="flex items-center gap-1 text-xs text-slate-600">
                <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />
                Tampilkan dibatalkan
              </label>
            </>
          ) : null}>
          {view === 'calendar' ? (
            schedules.loading && !schedules.data ? <Spinner /> : (
              <Suspense fallback={<Spinner />}>
                <ScheduleCalendar schedules={schedules.data ?? []} staleRuns={staleRuns}
                  showCancelled={showCancelled} lineId={lineId ? Number(lineId) : null}
                  onSelect={setSelectedId} onChanged={reloadAll} />
              </Suspense>
            )
          ) : (
            <ScheduleTable rows={schedules.data} loading={schedules.loading}
              onDetail={(s) => setSelectedId(s.id)} onEdit={(s) => setForm({ open: true, schedule: s })} />
          )}
        </Card>
        {view === 'calendar' && (
          <p className="-mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>Seret jadwal <b>Planned</b> untuk memindah tanggal.</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-primary-600" />Planned</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-amber-500" />In Progress</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-green-600" />Completed</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-slate-200" style={{ backgroundImage: 'repeating-linear-gradient(135deg, transparent 0 3px, rgb(0 0 0 / .15) 3px 6px)' }} />Rentang run basi</span>
          </p>
        )}
        <div ref={panelRef}><RunPlanningPanel schedules={schedules.data} prefill={prefill} /></div>
        <Card title="Riwayat Run" padded={false}>
          <PlanningRunList runs={runs.data} loading={runs.loading} />
        </Card>
      </div>

      {selected && (
        <ScheduleDrawer key={selected.id} schedule={selected} onClose={() => setSelectedId(null)}
          onChanged={reloadAll} onEdit={(s) => setForm({ open: true, schedule: s })} />
      )}
      <ScheduleFormModal open={form.open} schedule={form.schedule}
        onClose={() => setForm({ open: false, schedule: null })}
        onSaved={() => { setForm({ open: false, schedule: null }); reloadAll(); }} />
    </>
  );
}

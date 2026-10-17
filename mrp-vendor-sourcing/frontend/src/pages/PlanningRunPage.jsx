import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import StaleRunBanner from '../features/mps/StaleRunBanner';
import PageHeader from '../components/layout/PageHeader';
import Tabs from '../components/common/Tabs';
import EmptyState, { Spinner } from '../components/common/EmptyState';
import RunSummary from '../features/mps/RunSummary';
import PlanningResultTable from '../features/mps/PlanningResultTable';
import SourcingPanel from '../features/procurement/SourcingPanel';
import PoGeneratePanel from '../features/procurement/PoGeneratePanel';
import { usePlanningStore } from '../store/planningStore';
import { formatDate } from '../utils/formatters';

// Halaman kerja utama Phase 2–4: Hasil Planning · Sourcing · Purchase Order
export default function PlanningRunPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { run, lines, busy, error, loadRun } = usePlanningStore();
  const [tab, setTab] = useState('result');

  useEffect(() => { setTab('result'); loadRun(runId); }, [runId, loadRun]);

  if (error?.status === 404) {
    return <EmptyState title="Data tidak ditemukan" description={`Planning run #${runId} tidak ada.`}
      action={<Link className="text-indigo-700 underline" to="/mps">Kembali ke MPS</Link>} />;
  }
  if (busy || !run) return <Spinner />;

  const hasDeficit = lines.some((l) => l.shortfall > 0);
  return (
    <>
      <PageHeader title={`Planning Run #${run.id}`}
        subtitle={`${formatDate(run.date_from)} – ${formatDate(run.date_to)}`} />
      <StaleRunBanner run={run} onRerun={() => navigate('/mps')} />
      <RunSummary run={run} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: 'result', label: '1 Hasil Planning' },
        { id: 'sourcing', label: '2 Sourcing', disabled: !hasDeficit },
        { id: 'po', label: '3 Purchase Order', disabled: !hasDeficit },
      ]} />
      {tab === 'result' && <PlanningResultTable lines={lines} onNext={() => setTab('sourcing')} />}
      {tab === 'sourcing' && <SourcingPanel onNext={() => setTab('po')} />}
      {tab === 'po' && <PoGeneratePanel />}
    </>
  );
}

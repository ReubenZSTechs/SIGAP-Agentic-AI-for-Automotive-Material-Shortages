import { useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Card from '../../components/common/Card';
import Button from '../../components/common/Button';
import Icon from '../../components/common/Icon';
import Tabs from '../../components/common/Tabs';
import { Spinner } from '../../components/common/EmptyState';
import MissionList from '../../features/supplierHub/mission/MissionList';
import MissionDetail from '../../features/supplierHub/mission/MissionDetail';
import MissionWizard from '../../features/supplierHub/mission/MissionWizard';
import useDisclosure from '../../hooks/useDisclosure';
import useFetch from '../../hooks/useFetch';
import usePolling from '../../hooks/usePolling';
import { hubService } from '../../services/hubService';
import { useHubStore } from '../../store/hubStore';
import { toast } from '../../store/toastStore';

function MissionIndex() {
  const navigate = useNavigate();
  const refreshStatus = useHubStore((s) => s.refreshStatus);
  const [params, setParams] = useSearchParams();
  const poId = params.get('po');
  const wizard = useDisclosure(params.get('new') === '1');
  const { data, loading, error, reload } = useFetch(() => hubService.listMissions(), []);
  const [view, setView] = useState('ACTIVE');
  usePolling(reload, 15000);

  const rows = useMemo(() => (data ?? []).filter((m) => (view === 'ACTIVE' ? m.status !== 'DONE' && m.status !== 'CANCELLED' : m.status === 'DONE' || m.status === 'CANCELLED')), [data, view]);
  const activeCount = (data ?? []).filter((m) => m.status !== 'DONE' && m.status !== 'CANCELLED').length;

  return (
    <>
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3">
          <Tabs variant="segmented" value={view} onChange={setView} tabs={[{ id: 'ACTIVE', label: `Berjalan (${activeCount})` }, { id: 'DONE', label: 'Selesai' }]} />
          <Button className="ml-auto" onClick={wizard.show}><Icon name="plus" /> Misi baru</Button>
        </div>
        {error ? (
          <div className="p-4"><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></div>
        ) : loading && !data ? <Spinner /> : (
          <MissionList missions={rows} onOpen={(id) => navigate(`/supplier-hub/missions/${id}`)}
            emptyText={view === 'ACTIVE' ? 'Tidak ada misi berjalan. Mulai misi baru untuk bertanya ke beberapa supplier sekaligus.' : 'Belum ada misi selesai'} />
        )}
      </Card>
      <MissionWizard open={wizard.open} poId={poId} onClose={() => { wizard.hide(); if (poId) setParams({}, { replace: true }); }}
        onCreated={(ms) => {
          wizard.hide(); refreshStatus();
          const sent = ms.targets.filter((t) => t.state === 'SENT').length;
          const drafts = ms.targets.filter((t) => t.draft).length;
          const queued = ms.targets.filter((t) => t.state === 'QUEUED' && !t.draft).length;
          toast.success(`Misi #${ms.number} dimulai: ${sent} terkirim${drafts ? `, ${drafts} draf menunggu review` : ''}${queued ? `, ${queued} antre` : ''}`);
          navigate(`/supplier-hub/missions/${ms.id}`);
        }} />
    </>
  );
}

export default function HubMissions() {
  const { id } = useParams();
  return id ? <MissionDetail key={id} id={id} /> : <MissionIndex />;
}

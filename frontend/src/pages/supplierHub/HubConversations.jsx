import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Card from '../../components/common/Card';
import Button from '../../components/common/Button';
import Tabs from '../../components/common/Tabs';
import Input from '../../components/common/Input';
import { Spinner } from '../../components/common/EmptyState';
import ThreadList from '../../features/supplierHub/thread/ThreadList';
import ThreadView from '../../features/supplierHub/thread/ThreadView';
import useFetch from '../../hooks/useFetch';
import usePolling from '../../hooks/usePolling';
import { hubService } from '../../services/hubService';
import { t } from '../../i18n';

const FILTERS = [
  { id: 'ALL', label: 'Semua', test: () => true },
  { id: 'ACTION', label: 'Perlu tindakan', test: (item) => item.unread > 0 || item.drafts > 0 || item.failed > 0 },
  { id: 'HUMAN', label: 'Diambil alih', test: (item) => item.mode === 'HUMAN' },
];

function ThreadIndex() {
  const navigate = useNavigate();
  const { data, loading, error, reload } = useFetch(() => hubService.listThreads(), []);
  const [filter, setFilter] = useState('ALL');
  const [q, setQ] = useState('');
  usePolling(reload, 15000);

  const rows = useMemo(() => {
    const f = FILTERS.find((x) => x.id === filter);
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((item) => f.test(item) && (!needle || item.supplier.name.toLowerCase().includes(needle) || item.refs.some((r) => r.toLowerCase().includes(needle))));
  }, [data, filter, q]);
  const actionCount = (data ?? []).filter(FILTERS[1].test).length;

  return (
    <Card padded={false}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3">
        <Tabs variant="segmented" value={filter} onChange={setFilter}
          tabs={FILTERS.map((f) => ({ id: f.id, label: f.id === 'ACTION' && actionCount ? `${t(f.label)} (${actionCount})` : f.label }))} />
        <Input className="h-8 sm:ml-auto sm:w-64" placeholder={t('Cari supplier atau nomor PO')} aria-label={t('Cari percakapan')} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error ? (
        <div className="p-4"><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>{t('Coba lagi')}</Button></div>
      ) : loading && !data ? <Spinner /> : (
        <ThreadList threads={rows} onOpen={(tid) => navigate(`/supplier-hub/conversations/${tid}`)}
          emptyText={filter === 'ALL' && !q ? t('Belum ada percakapan dengan supplier') : t('Tidak ada percakapan yang cocok')} />
      )}
    </Card>
  );
}

export default function HubConversations() {
  const { id } = useParams();
  return id ? <ThreadView key={id} id={id} /> : <ThreadIndex />;
}

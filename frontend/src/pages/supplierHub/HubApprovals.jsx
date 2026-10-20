import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Card from '../../components/common/Card';
import Button from '../../components/common/Button';
import Icon from '../../components/common/Icon';
import Tabs from '../../components/common/Tabs';
import EmptyState, { Spinner } from '../../components/common/EmptyState';
import { Select } from '../../components/common/Input';
import ApprovalList from '../../features/supplierHub/ApprovalList';
import ApprovalCard from '../../features/supplierHub/ApprovalCard';
import DecisionModal from '../../features/supplierHub/DecisionModal';
import { TYPE, isUrgent } from '../../features/supplierHub/meta';
import usePolling from '../../hooks/usePolling';
import { useHubStore } from '../../store/hubStore';
import { toast } from '../../store/toastStore';

const DONE_COPY = { approve: 'Disetujui', reject: 'Ditolak', revision: 'Revisi dicatat', choose: 'Opsi dijalankan' };

function Stat({ label, value, warn }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-0.5 text-2xl font-bold tabular-nums ${warn && value > 0 ? 'text-amber-700' : 'text-slate-900'}`}>{value}</div>
    </div>
  );
}

// Inbox Persetujuan (default). Deep link: /supplier-hub?item=ap-102
export default function HubApprovals() {
  const { items, loading, error, load, decide } = useHubStore();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState('PENDING');
  const [type, setType] = useState('');
  const [dlg, setDlg] = useState(null); // { mode, payload }
  const selectedId = params.get('item');
  const setSelectedId = (id) => setParams(id ? { item: id } : {}, { replace: true });

  useEffect(() => { load(); }, [load]);
  usePolling(() => load(true), 15000);

  const pendingItems = useMemo(() => items.filter((i) => i.status === 'PENDING'), [items]);
  const visible = useMemo(
    () => items.filter((i) => (view === 'PENDING' ? i.status === 'PENDING' : i.status !== 'PENDING') && (!type || i.type === type)),
    [items, view, type],
  );
  const selected = items.find((i) => i.id === selectedId) ?? null;

  useEffect(() => { // deep link ke item yang sudah diputuskan: tampilkan daftar Selesai
    if (selected && selected.status !== 'PENDING' && view === 'PENDING') setView('DONE');
  }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // desktop: pilih item pertama otomatis
    if (!selectedId && visible.length && window.matchMedia('(min-width: 1024px)').matches) setSelectedId(visible[0].id);
  }, [visible, selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async ({ approver, reason }) => {
    const { mode, payload } = dlg;
    try {
      await decide(selected.id, mode, { ...payload, approver, reason });
      toast.success(DONE_COPY[mode]);
      setDlg(null); setSelectedId(null);
    } catch (e) { toast.error(e.message ?? 'Gagal menyimpan keputusan'); if (e.status === 409) setDlg(null); }
  };

  return (
    <>
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Menunggu" value={pendingItems.length} />
        <Stat label="Hampir kedaluwarsa" value={pendingItems.filter(isUrgent).length} warn />
        <Stat label="Risiko tinggi" value={pendingItems.filter((i) => i.risk === 'HIGH').length} warn />
        <Stat label="Sudah diputuskan" value={items.length - pendingItems.length} />
      </div>

      {error ? (
        <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={() => load()}>Coba lagi</Button></Card>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <div className={selected ? 'hidden lg:block' : ''}>
            <Card padded={false}>
              <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3">
                <Tabs variant="segmented" value={view} onChange={(v) => { setView(v); setSelectedId(null); }}
                  tabs={[{ id: 'PENDING', label: 'Menunggu' }, { id: 'DONE', label: 'Selesai' }]} />
                <Select className="ml-auto h-8 w-auto! min-w-0 text-xs" value={type} aria-label="Filter jenis" onChange={(e) => { setType(e.target.value); setSelectedId(null); }}>
                  <option value="">Semua jenis</option>
                  {Object.entries(TYPE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </Select>
              </div>
              {loading && !items.length ? <Spinner /> : (
                <ApprovalList items={visible} selectedId={selectedId} onSelect={setSelectedId}
                  emptyText={view === 'PENDING' ? 'Tidak ada yang perlu disetujui' : 'Belum ada keputusan'} />
              )}
            </Card>
          </div>

          <div className={selected ? '' : 'hidden lg:block'}>
            {selected ? (
              <>
                <Button className="mb-3 lg:hidden" variant="ghost" size="sm" onClick={() => setSelectedId(null)}><Icon name="arrowLeft" /> Kembali</Button>
                <ApprovalCard key={`${selected.id}-${selected.version}`} item={selected} onDecide={(mode, payload) => setDlg({ mode, payload })} />
              </>
            ) : <Card><EmptyState title="Pilih item untuk ditinjau" description="Perubahan, bukti dari chat, dan dampaknya tampil di sini." /></Card>}
          </div>
        </div>
      )}

      <DecisionModal open={!!dlg} mode={dlg?.mode} item={selected} onClose={() => setDlg(null)} onSubmit={submit}
        detail={dlg?.mode === 'choose' ? `Opsi: ${dlg.payload.label}. Keputusan ini sama dengan menekan tombol di Telegram manajer.` : null} />
    </>
  );
}

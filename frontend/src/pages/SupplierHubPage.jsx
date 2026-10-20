import { useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import Button from '../components/common/Button';
import Icon from '../components/common/Icon';
import Tabs from '../components/common/Tabs';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { approverName } from '../features/supplierHub/meta';
import useDisclosure from '../hooks/useDisclosure';
import { useHubStore } from '../store/hubStore';
import { toast } from '../store/toastStore';

// Cangkang Hub: header status Agent & Telegram, banner global, dan tab per sub-route.
const SECTIONS = [
  { id: '', label: 'Persetujuan', count: (s) => s.pending },
  { id: 'conversations', label: 'Percakapan', count: (s) => s.counts.threads },
  { id: 'missions', label: 'Misi', count: (s) => s.counts.missions },
  { id: 'documents', label: 'Dokumen', count: (s) => s.counts.documents },
  { id: 'settings', label: 'Pengaturan' },
];

export default function SupplierHubPage() {
  const hub = useHubStore();
  const { pending, paused, telegram, aiConfigured, refreshStatus, setPaused } = hub;
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const pauseDlg = useDisclosure();
  const section = pathname.split('/')[2] ?? '';

  useEffect(() => { refreshStatus(); }, [refreshStatus, pathname]);
  useEffect(() => { // tab browser menampilkan jumlah menunggu
    document.title = `${pending ? `(${pending}) ` : ''}Hub Supplier`;
    return () => { document.title = 'MRP & Vendor Sourcing'; };
  }, [pending]);

  const togglePause = async () => {
    try { await setPaused(!paused, approverName()); toast.success(paused ? 'Agent dilanjutkan' : 'Agent dijeda'); } catch (e) { toast.error(e.message); }
    pauseDlg.hide();
  };
  const tabs = SECTIONS.map((s) => {
    const n = s.count?.(hub);
    return { id: s.id, label: n ? `${s.label} (${n})` : s.label };
  });
  const tgDown = telegram && !telegram.connected;
  const sandbox = telegram?.mode === 'sandbox';

  return (
    <>
      <PageHeader title="Hub Supplier" subtitle="Setujui, awasi, dan ambil alih komunikasi Agent dengan supplier lewat Telegram"
        actions={(
          <>
            <span className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-200" role="status">
              <i className={`h-2 w-2 rounded-full ${paused ? 'bg-amber-500' : 'bg-green-600'}`} />{paused ? 'Agent dijeda' : 'Agent aktif'}
            </span>
            {telegram && (
              <span className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-200" role="status">
                <Icon name="send" className={`h-4 w-4 ${tgDown ? 'text-red-600' : 'text-slate-500'}`} />
                {sandbox ? 'Telegram: sandbox' : `Telegram ${tgDown ? 'terputus' : 'OK'}`}
              </span>
            )}
            <Button variant="secondary" onClick={paused ? togglePause : pauseDlg.show}>
              <Icon name={paused ? 'play' : 'pause'} /> {paused ? 'Lanjutkan' : 'Jeda Agent'}
            </Button>
          </>
        )} />

      {tgDown && (
        <div role="alert" className="mb-4 flex flex-wrap items-center gap-2.5 rounded-xl border border-red-200 border-l-4 border-l-red-600 bg-red-50 px-4 py-3 text-sm text-red-900">
          <Icon name="alert" className="h-4 w-4 text-red-600" />
          <span className="flex-1">Bot Telegram belum aktif (TELEGRAM_MODE=telegram tanpa token). {telegram.unsent} pesan gagal terkirim dalam 24 jam terakhir.</span>
          <Button size="sm" variant="secondary" onClick={() => navigate('/supplier-hub/settings?tab=telegram')}>Periksa koneksi</Button>
        </div>
      )}
      {telegram && !tgDown && telegram.unsent > 0 && (
        <div role="status" className="mb-4 flex flex-wrap items-center gap-2.5 rounded-xl border border-red-200 border-l-4 border-l-red-600 bg-red-50 px-4 py-3 text-sm text-red-900">
          <Icon name="alert" className="h-4 w-4 text-red-600" />
          <span className="flex-1">{telegram.unsent} pesan gagal terkirim dalam 24 jam terakhir. Buka thread terkait untuk mengirim ulang.</span>
          <Button size="sm" variant="secondary" onClick={() => navigate('/supplier-hub/conversations')}>Lihat percakapan</Button>
        </div>
      )}
      {telegram && !aiConfigured && (
        <div role="status" className="mb-4 flex items-start gap-2.5 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
          <Icon name="info" className="mt-0.5 h-4 w-4 text-primary-600" />
          <span>AI Core belum dikonfigurasi (AICORE_* di backend/.env). Data dan keputusan tetap bisa dipakai, tetapi balasan supplier tidak diproses Agent.</span>
        </div>
      )}
      {paused && (
        <div role="alert" className="mb-4 flex flex-wrap items-center gap-2.5 rounded-xl border border-amber-200 border-l-4 border-l-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <Icon name="alert" className="h-4 w-4 text-amber-600" />
          <span className="flex-1">Agent Hub dijeda: misi, pengingat, dan draf tidak dikirim ke supplier sampai dilanjutkan. Agent PO tetap menjawab konfirmasi/revisi PO.</span>
          <Button size="sm" variant="secondary" onClick={togglePause}><Icon name="play" /> Lanjutkan</Button>
        </div>
      )}

      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Tabs tabs={tabs} value={section} onChange={(id) => navigate(id ? `/supplier-hub/${id}` : '/supplier-hub')} />
      </div>

      <Outlet />

      <ConfirmDialog open={pauseDlg.open} title="Jeda Agent" variant="primary" confirmLabel="Jeda"
        message="Misi, pengingat, dan draf Hub berhenti dikirim sampai Anda melanjutkannya. Agent PO (konfirmasi & revisi PO) tetap berjalan, dan persetujuan tetap bisa diputuskan."
        onConfirm={togglePause} onCancel={pauseDlg.hide} />
    </>
  );
}

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../../components/common/Button';
import Card from '../../../components/common/Card';
import DataTable from '../../../components/common/DataTable';
import Icon from '../../../components/common/Icon';
import StateBadge from '../StateBadge';
import SupplierConnectModal from './SupplierConnectModal';
import { TELEGRAM } from '../meta';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { useHubStore } from '../../../store/hubStore';

// Status bot dan koneksi Telegram per supplier (memakai tautan /start dari agent Telegram yang sudah ada).
export default function TelegramSettings() {
  const navigate = useNavigate();
  const telegram = useHubStore((s) => s.telegram);
  const { data, loading, error, reload } = useFetch(() => hubService.listSuppliers(), []);
  const [connecting, setConnecting] = useState(null);
  const sandbox = telegram?.mode === 'sandbox';

  const columns = [
    { key: 'name', header: 'Supplier', render: (s) => <span><span className="block font-medium text-slate-800">{s.name}</span><span className="font-mono text-xs text-slate-500">{s.code}</span></span> },
    { key: 'contact', header: 'Kontak', render: (s) => s.contact_raw || '—' },
    { key: 'telegram', header: 'Telegram', render: (s) => (
      <span className="inline-flex flex-wrap items-center gap-2"><StateBadge meta={TELEGRAM[s.telegram]} />{s.sandbox && <span className="text-xs text-slate-500">sandbox</span>}</span>
    ) },
    { key: 'resp', header: 'Respons rata-rata', align: 'right', className: 'tabular-nums text-slate-600', render: (s) => (s.avg_response_min != null ? `${s.avg_response_min} mnt` : '—') },
    { key: 'actions', header: 'Aksi', align: 'right', render: (s) => (
      <span className="inline-flex gap-1">
        {s.telegram !== 'CONNECTED' && <Button size="sm" variant="secondary" onClick={() => setConnecting(s)}><Icon name="link" /> {s.telegram === 'PENDING' ? 'Kirim ulang undangan' : 'Hubungkan'}</Button>}
        {s.thread_id && <Button size="sm" variant="ghost" onClick={() => navigate(`/supplier-hub/conversations/${s.thread_id}`)}><Icon name="chat" /> Buka chat</Button>}
      </span>
    ) },
  ];
  const connected = (data ?? []).filter((s) => s.telegram === 'CONNECTED').length;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-900 text-white"><Icon name="send" className="h-5 w-5" /></span>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-slate-900">{sandbox ? 'Mode sandbox' : `@${telegram?.bot ?? 'bot belum diatur'}`}</p>
            <p className="text-sm text-slate-500">
              {sandbox ? 'Pesan hanya disimpan di database; balasan supplier disimulasikan dari Hub atau Telegram Lab.' : telegram?.live ? 'Bot Telegram aktif (worker long polling).' : 'TELEGRAM_BOT_TOKEN belum diisi.'}
              {' · '}{connected} dari {data?.length ?? 0} supplier terhubung
            </p>
          </div>
          <StateBadge meta={telegram?.connected ? { label: sandbox ? 'Sandbox aktif' : 'Bot aktif', tone: 'green' } : { label: 'Bot belum aktif', tone: 'red' }} />
        </div>
      </Card>

      <Card padded={false} title="Koneksi supplier">
        {error ? <div className="p-4"><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></div>
          : <DataTable columns={columns} rows={data} loading={loading && !data} emptyText="Belum ada supplier" />}
      </Card>

      <SupplierConnectModal supplier={connecting} onClose={() => { setConnecting(null); reload(); }} onConnected={reload} />
    </div>
  );
}

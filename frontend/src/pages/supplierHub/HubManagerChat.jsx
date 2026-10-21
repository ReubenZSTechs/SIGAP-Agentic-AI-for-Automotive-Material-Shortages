import { Fragment, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import Icon from '../../components/common/Icon';
import { Textarea } from '../../components/common/Input';
import { Spinner } from '../../components/common/EmptyState';
import ManagerMessage from '../../features/supplierHub/manager/ManagerMessage';
import { approverName, dayLabel } from '../../features/supplierHub/meta';
import useFetch from '../../hooks/useFetch';
import usePolling from '../../hooks/usePolling';
import { hubService } from '../../services/hubService';
import { useHubStore } from '../../store/hubStore';
import { toast } from '../../store/toastStore';

// Cermin chat Telegram manajer. Tombol dan balasan di sini berjalan lewat jalur yang sama dengan Telegram,
// lalu tombol yang sudah tidak berlaku dihapus di Telegram (dan sebaliknya), jadi kedua sisi tetap sinkron.
export default function HubManagerChat() {
  const navigate = useNavigate();
  const { refreshStatus, aiConfigured } = useHubStore();
  const { data, error, reload } = useFetch(() => hubService.managerMessages(), []);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(null);
  const scroller = useRef(null);
  usePolling(reload, 5000);

  const count = data?.messages.length ?? 0;
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [count]);

  const run = async (key, fn) => {
    setBusy(key);
    try { await fn(); await reload(); refreshStatus(); return true; } catch (e) { toast.error(e.message); await reload(); return false; } finally { setBusy(null); }
  };
  const press = (b) => run(b.data, () => hubService.managerPress(b.data, approverName()));
  const send = async () => {
    const body = text.trim();
    if (body && await run('send', () => hubService.managerSend(body, approverName()))) setText('');
  };

  if (error && !data) return <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>Coba lagi</Button></Card>;
  if (!data) return <Spinner />;

  let lastDay = null;
  return (
    <>
      {!data.manager_chat && (
        <div role="status" className="mb-3 flex items-start gap-2.5 rounded-xl border border-amber-200 border-l-4 border-l-amber-500 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
          <Icon name="alert" className="mt-0.5 h-4 w-4 text-amber-600" />
          <span>TELEGRAM_MANAGER_CHAT_ID belum diisi: pesan agent untuk manajer hanya tampil di sini, tidak terkirim ke Telegram.</span>
        </div>
      )}
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3 text-sm">
          <Icon name="send" className="h-4 w-4 text-slate-500" />
          <span className="font-semibold text-slate-900">Chat manajer</span>
          <span className="text-slate-500">· {data.mode === 'sandbox' ? 'sandbox' : 'tersinkron dengan Telegram'}</span>
          {data.pending > 0 && <span className="ml-auto text-xs font-medium text-amber-700">{data.pending} revisi menunggu keputusan</span>}
        </div>
        <div ref={scroller} className="h-[calc(100dvh-24rem)] min-h-[22rem] overflow-y-auto bg-slate-50/70 px-3 py-3 sm:px-5" aria-live="polite" aria-label="Isi chat manajer">
          {data.messages.length === 0 && <p className="py-10 text-center text-sm text-slate-500">Belum ada pesan untuk manajer.</p>}
          {data.messages.map((m) => {
            const day = dayLabel(m.at);
            const sep = day !== lastDay;
            lastDay = day;
            return (
              <Fragment key={m.id}>
                {sep && <div className="my-4 flex items-center gap-3 text-xs font-medium text-slate-500"><span className="h-px flex-1 bg-slate-200" />{day}<span className="h-px flex-1 bg-slate-200" /></div>}
                <ManagerMessage m={m} busy={busy} onPress={press} onOpenApproval={(id) => navigate(`/supplier-hub?item=${id}`)} />
              </Fragment>
            );
          })}
        </div>
        <div className="border-t border-slate-200 bg-white px-4 py-3">
          <Textarea rows={2} value={text} aria-label="Balasan manajer" disabled={!aiConfigured}
            placeholder={aiConfigured ? 'Balas seperti di Telegram, mis. "setujui saja revisinya"…' : 'AI Core belum dikonfigurasi: gunakan tombol opsi'}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500">Balasan teks selalu diminta konfirmasi lewat tombol sebelum dijalankan. Pesan Anda juga tampil di Telegram manajer.</span>
            <Button size="sm" className="ml-auto" loading={busy === 'send'} disabled={!text.trim() || !aiConfigured} onClick={send}><Icon name="send" /> Kirim</Button>
          </div>
        </div>
      </Card>
    </>
  );
}

import { Fragment, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../../components/common/Button';
import Card from '../../../components/common/Card';
import Icon from '../../../components/common/Icon';
import Input from '../../../components/common/Input';
import { Spinner } from '../../../components/common/EmptyState';
import StateBadge from '../StateBadge';
import MessageBubble from './MessageBubble';
import ThreadComposer from './ThreadComposer';
import ContextPanel from './ContextPanel';
import AttachmentPreview from './AttachmentPreview';
import { Avatar } from './ThreadList';
import { THREAD_MODE, TELEGRAM, approverName, clock, dayLabel } from '../meta';
import useDisclosure from '../../../hooks/useDisclosure';
import useFetch from '../../../hooks/useFetch';
import usePolling from '../../../hooks/usePolling';
import { hubService } from '../../../services/hubService';
import { useHubStore } from '../../../store/hubStore';
import { toast } from '../../../store/toastStore';
import { t } from '../../../i18n';

// Mode sandbox: berperan sebagai supplier lewat jalur yang sama dengan pesan Telegram.
function SandboxReply({ supplierId, onDone }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try { await hubService.sandboxReply(supplierId, text.trim()); setText(''); onDone(); } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-dashed border-slate-300 bg-slate-50 px-4 py-2.5">
      <span className="text-xs font-medium text-slate-500">{t('Simulasi supplier (sandbox)')}</span>
      <Input className="h-8 min-w-0 flex-1 text-xs" placeholder={t('Ketik balasan seolah-olah dari supplier…')} value={text}
        onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && text.trim()) send(); }} />
      <Button size="sm" variant="secondary" loading={busy} disabled={!text.trim()} onClick={send}>{t('Kirim sebagai supplier')}</Button>
    </div>
  );
}

// Thread percakapan per supplier: gelembung pesan, ambil alih / serahkan ke Agent, panel konteks (kolom di >=1280px, drawer di bawahnya).
export default function ThreadView({ id }) {
  const navigate = useNavigate();
  const { refreshStatus, telegram } = useHubStore();
  const { data: thread, error, reload } = useFetch(() => hubService.getThread(id), [id]);
  const [busy, setBusy] = useState(null);
  const [preview, setPreview] = useState(null);
  const ctx = useDisclosure();
  const scroller = useRef(null);
  usePolling(reload, 10000);

  const count = thread?.messages.length ?? 0;
  useEffect(() => { // gulir ke pesan terbaru saat dibuka dan saat ada pesan baru
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [count]);

  const run = async (key, fn, ok) => {
    setBusy(key);
    try { await fn(); if (ok) toast.success(ok); await reload(); refreshStatus(); return true; } catch (e) { toast.error(e.message); return false; } finally { setBusy(null); }
  };
  const me = approverName();
  const takeover = () => run('takeover', () => hubService.takeover(id, me), 'Anda mengambil alih percakapan. Agent dijeda untuk supplier ini.');
  const release = () => run('release', () => hubService.release(id, me), 'Percakapan diserahkan kembali ke Agent');

  if (error && !thread) return <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>{t('Coba lagi')}</Button></Card>;
  if (!thread) return <Spinner />;

  const sandbox = telegram?.mode === 'sandbox' && thread.supplier.sandbox;
  let lastDay = null;
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button variant="ghost" size="sm" onClick={() => navigate('/supplier-hub/conversations')}><Icon name="arrowLeft" /> {t('Percakapan')}</Button>
        <Avatar name={thread.supplier.name} size="h-8 w-8" />
        <div className="min-w-0">
          <h2 className="truncate text-base font-bold text-slate-900">{thread.supplier.name}</h2>
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1"><Icon name="send" className="h-3 w-3" /> {t('Telegram {state}', { state: t(TELEGRAM[thread.supplier.telegram].label).toLowerCase() })}{thread.supplier.sandbox ? ' (sandbox)' : ''}</span>
            {thread.context.pos.slice(0, 2).map((p) => <span key={p.id} className="font-mono">{p.po_number}</span>)}
          </p>
        </div>
        <StateBadge meta={THREAD_MODE[thread.mode]} />
        <div className="ml-auto flex gap-2">
          <Button variant="secondary" className="xl:hidden" onClick={ctx.show}><Icon name="info" /> {t('Konteks')}</Button>
          {thread.mode === 'AGENT'
            ? <Button variant="secondary" loading={busy === 'takeover'} onClick={takeover}><Icon name="user" /> {t('Ambil alih')}</Button>
            : <Button variant="secondary" loading={busy === 'release'} onClick={release}><Icon name="spark" /> {t('Serahkan ke Agent')}</Button>}
        </div>
      </div>

      {thread.mode === 'HUMAN' && (
        <div role="status" className="mb-3 flex flex-wrap items-center gap-2.5 rounded-xl border border-amber-200 border-l-4 border-l-amber-500 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
          <Icon name="pause" className="h-4 w-4 text-amber-600" />
          <span className="flex-1">{t('Agent dijeda untuk supplier ini')}{thread.taken_over_by ? ` ${t('sejak {time}, diambil alih oleh {name}', { time: clock(thread.taken_over_at), name: thread.taken_over_by })}` : ''}. {t('Balasan supplier hanya dicatat.')}</span>
          <Button size="sm" variant="secondary" loading={busy === 'release'} onClick={release}>{t('Serahkan kembali ke Agent')}</Button>
        </div>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <Card padded={false}>
          <div ref={scroller} className="h-[calc(100dvh-24rem)] min-h-[22rem] overflow-y-auto bg-slate-50/70 px-3 py-3 sm:px-5" aria-live="polite" aria-label={t('Isi percakapan')}>
            {thread.messages.length === 0 && <p className="py-10 text-center text-sm text-slate-500">{t('Belum ada pesan dengan supplier ini.')}</p>}
            {thread.messages.map((m) => {
              const day = dayLabel(m.at);
              const sep = day !== lastDay;
              lastDay = day;
              return (
                <Fragment key={m.id}>
                  {sep && <div className="my-4 flex items-center gap-3 text-xs font-medium text-slate-500"><span className="h-px flex-1 bg-slate-200" />{day}<span className="h-px flex-1 bg-slate-200" /></div>}
                  <MessageBubble m={m} supplier={thread.supplier} busy={busy}
                    onOpenApproval={(aid) => navigate(`/supplier-hub?item=${aid}`)}
                    onOpenMission={(mid) => navigate(`/supplier-hub/missions/${mid}`)}
                    onOpenManager={() => navigate('/supplier-hub/manager')}
                    onOpenAttachment={setPreview}
                    onSendDraft={(msg, text) => run(`send-${msg.id}`, () => hubService.sendDraft(msg.outbox_id, text, me), t('Draf dikirim ke supplier'))}
                    onDiscard={(msg) => run(`discard-${msg.id}`, () => hubService.discardDraft(msg.outbox_id, me), t('Draf dibuang'))}
                    onRetry={(msg) => run(`retry-${msg.id}`, () => hubService.retryMessage(msg.message_id, me), t('Pesan dikirim ulang'))} />
                </Fragment>
              );
            })}
          </div>
          <ThreadComposer thread={thread} busy={busy} onTakeover={takeover}
            onSend={(text) => run('send', () => hubService.sendMessage(id, text, me))} />
          {sandbox && <SandboxReply supplierId={id} onDone={() => { reload(); refreshStatus(); }} />}
        </Card>
        <div className="hidden xl:block"><ContextPanel thread={thread} /></div>
      </div>

      {ctx.open && (
        <div className="fixed inset-0 z-40 xl:hidden">
          <div className="anim-fade absolute inset-0 bg-primary-950/40" onClick={ctx.hide} />
          <aside aria-label={t('Konteks percakapan')} className="anim-slide absolute inset-y-0 right-0 w-full max-w-[360px] overflow-y-auto bg-slate-50 p-4 shadow-2xl">
            <header className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">{t('Konteks')}</h2>
              <button onClick={ctx.hide} aria-label={t('Tutup panel')} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="x" className="h-5 w-5" /></button>
            </header>
            <ContextPanel thread={thread} />
          </aside>
        </div>
      )}
      <AttachmentPreview attachment={preview} onClose={() => setPreview(null)} />
    </>
  );
}

import Icon from '../../../components/common/Icon';
import { initials, shortTime } from '../meta';
import { t } from '../../../i18n';

const PREFIX = { AGENT: 'Agent: ', ADMIN: 'Anda: ', SUPPLIER: '' };

export function Avatar({ name, size = 'h-10 w-10' }) {
  return <span className={`flex shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-600 ${size}`} aria-hidden="true">{initials(name)}</span>;
}

// Baris thread: supplier, cuplikan pesan terakhir, dan sinyal yang perlu tindakan (draf, gagal, belum dibaca).
export default function ThreadList({ threads, onOpen, emptyText }) {
  if (threads.length === 0) return <p className="px-4 py-10 text-center text-sm text-slate-500">{emptyText}</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {threads.map((thread) => {
        const last = thread.last;
        const prefix = last?.status === 'DRAFT' ? `${t('Draf')}: ` : t(PREFIX[last?.from] ?? '');
        return (
          <li key={thread.id}>
            <button type="button" onClick={() => onOpen(thread.id)} className="flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors hover:bg-slate-50">
              <Avatar name={thread.supplier.name} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className={`truncate text-sm ${thread.unread ? 'font-bold text-slate-900' : 'font-semibold text-slate-800'}`}>{thread.supplier.name}</span>
                  {thread.mode === 'HUMAN' && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-amber-50 px-1.5 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
                      <Icon name="user" className="h-3 w-3" /> Diambil alih
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-xs tabular-nums text-slate-500">{shortTime(thread.last_at)}</span>
                </span>
                <span className={`mt-0.5 block truncate text-sm ${thread.unread ? 'text-slate-800' : 'text-slate-500'}`}>
                  {last ? <><span className="text-slate-400">{prefix}</span>{last.text}</> : t('Belum ada pesan')}
                </span>
                {(thread.drafts > 0 || thread.failed > 0 || thread.refs.length > 0) && (
                  <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    {thread.drafts > 0 && <span className="inline-flex items-center gap-1 font-medium text-primary-700"><Icon name="edit" className="h-3 w-3" />{t('{n} draf perlu review', { n: thread.drafts })}</span>}
                    {thread.failed > 0 && <span className="inline-flex items-center gap-1 font-medium text-red-700"><Icon name="alert" className="h-3 w-3" />{t('{n} gagal terkirim', { n: thread.failed })}</span>}
                    {thread.refs.map((r) => <span key={r} className="font-mono text-slate-500">{r}</span>)}
                  </span>
                )}
              </span>
              {thread.unread > 0 && (
                <span className="mt-0.5 rounded-full bg-primary-600 px-1.5 text-xs font-bold text-white" aria-label={t('{n} pesan belum dibaca', { n: thread.unread })}>{thread.unread}</span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

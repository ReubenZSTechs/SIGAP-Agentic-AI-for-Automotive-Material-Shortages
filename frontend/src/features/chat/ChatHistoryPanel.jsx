import Button from '../../components/common/Button';
import { Spinner } from '../../components/common/EmptyState';
import Icon from '../../components/common/Icon';
import { formatDateTime, timeAgo } from '../../utils/formatters';
import { t } from '../../i18n';

/**
 * Daftar percakapan lampau di samping chat: pilih untuk membuka ulang, tombol sampah untuk menghapus satu,
 * Percakapan yang sedang dijalankan Agent tidak bisa dihapus.
 */
export default function ChatHistoryPanel({ threads, loading, error, activeId, busy, onOpen, onDelete, onRetry, onClose }) {
  const items = threads ?? [];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">{t('Riwayat percakapan')}</h2>
        {items.length > 0 && <span className="rounded-full bg-slate-100 px-2 text-xs font-medium tabular-nums text-slate-600">{items.length}</span>}
        <button
          type="button"
          onClick={onClose}
          aria-label={t('Tutup riwayat')}
          className="-mr-1 ml-auto rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 md:hidden"
        >
          <Icon name="x" className="h-4 w-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {error && !threads ? (
          <div className="p-4">
            <p className="text-sm text-red-600">{error.message}</p>
            <Button className="mt-3" size="sm" variant="secondary" onClick={onRetry}>{t('Coba lagi')}</Button>
          </div>
        ) : loading && !threads ? (
          <Spinner />
        ) : items.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-slate-500">{t('Belum ada riwayat percakapan. Percakapan Anda akan muncul di sini setelah Anda mengirim pesan.')}</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {items.map((th) => {
              const active = th.thread_id === activeId;
              const locked = active && busy;     // Agent masih menulis ke percakapan ini
              return (
                <li key={th.thread_id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onOpen(th.thread_id)}
                    aria-current={active ? 'true' : undefined}
                    className={`flex w-full flex-col gap-0.5 py-3 pl-4 pr-11 text-left transition-colors ${active ? 'bg-primary-50' : 'hover:bg-slate-50'}`}
                  >
                    <span className={`line-clamp-2 break-words text-sm ${active ? 'font-semibold text-primary-800' : 'font-medium text-slate-800'}`}>{th.title}</span>
                    <span className="text-xs text-slate-500" title={formatDateTime(th.updated_at)}>{timeAgo(th.updated_at)}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(th)}
                    disabled={locked}
                    aria-label={`${t('Hapus percakapan')}: ${th.title}`}
                    title={locked ? t('Tunggu Agent selesai sebelum menghapus percakapan ini') : t('Hapus percakapan')}
                    className="absolute right-2 top-2.5 rounded-lg p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-400 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100"
                  >
                    <Icon name="trash" className="h-4 w-4" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

    </div>
  );
}
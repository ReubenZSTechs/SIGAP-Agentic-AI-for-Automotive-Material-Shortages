import Icon from '../../../components/common/Icon';
import { AgentTile } from '../thread/MessageBubble';
import { MSG_STATUS, clock } from '../meta';
import { t } from '../../../i18n';

const SOURCE = { telegram: 'via Telegram', hub: 'via Hub' };
const BUTTON = {
  active: 'bg-white text-primary-700 ring-primary-300 hover:bg-primary-50',
  chosen: 'bg-green-50 text-green-800 ring-green-300',
  closed: 'bg-slate-50 text-slate-400 ring-slate-200 line-through',
};

// Satu pesan di chat manajer: agent di kiri (seperti di Telegram, dengan tombol opsi), manajer di kanan.
// Status tombol berasal dari status permintaan revisi, jadi pilihan di Telegram atau di Hub tampil sama.
export default function ManagerMessage({ m, busy, onPress, onOpenApproval }) {
  if (m.from === 'MANAGER') {
    return (
      <div className="my-2 flex justify-end">
        <div className="w-fit max-w-[min(34rem,88%)]">
          <div className="mb-1 flex items-center justify-end gap-1.5 text-xs text-slate-500">
            <Icon name="user" className="h-3.5 w-3.5" /><b className="font-semibold text-slate-700">{m.author || 'Manajer'}</b>
            <span>· {t(SOURCE[m.source] ?? m.source)}</span>
          </div>
          <div className="rounded-2xl rounded-tr-md bg-white px-3.5 py-2.5 text-sm text-slate-800 ring-1 ring-inset ring-primary-400">
            <p className="whitespace-pre-line">{m.text}</p>
          </div>
          <div className="mt-1 text-right text-xs tabular-nums text-slate-500">{clock(m.at)}</div>
        </div>
      </div>
    );
  }

  const status = MSG_STATUS[m.status];
  return (
    <div className="my-2 flex justify-start">
      <div className="w-fit max-w-[min(38rem,92%)]">
        <div className="mb-1 flex items-center gap-1.5 text-xs text-slate-500"><AgentTile /> <b className="font-semibold text-slate-700">{t('Agent')}</b></div>
        <div className="rounded-2xl rounded-tl-md bg-primary-50 px-3.5 py-2.5 text-sm text-slate-800 ring-1 ring-inset ring-primary-100">
          <p className="whitespace-pre-line">{m.text}</p>
          {m.buttons.length > 0 && (
            <div className="mt-3 flex flex-col gap-1.5">
              {m.buttons.map((b) => (
                <button key={b.data} type="button" disabled={b.state !== 'active' || !!busy} onClick={() => onPress(b)}
                  className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition disabled:cursor-not-allowed ${BUTTON[b.state]} ${busy === b.data ? 'opacity-60' : ''}`}>
                  {b.state === 'chosen' && <Icon name="check" className="h-3.5 w-3.5" />}{t(b.label)}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
          {status && <span className={`inline-flex items-center gap-0.5 ${m.status === 'FAILED' ? 'text-red-700' : ''}`}><Icon name={status.icon} className="h-3.5 w-3.5" />{t(status.label)}{m.error ? `: ${m.error}` : ''}</span>}
          <span className="tabular-nums">{clock(m.at)}</span>
          {m.approval_ids.map((id) => (
            <button key={id} type="button" onClick={() => onOpenApproval(id)} className="font-medium text-primary-700 hover:underline">Kartu revisi #{id.slice(3)}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

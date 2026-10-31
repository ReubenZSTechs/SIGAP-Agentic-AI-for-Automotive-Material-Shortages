import Icon from '../../components/common/Icon';
import { RISK, isUrgent, timeLeft, typeMeta } from './meta';
import { t } from '../../i18n';

const DOT = { LOW: 'bg-slate-400', MEDIUM: 'bg-amber-500', HIGH: 'bg-red-500' };

export default function ApprovalList({ items, selectedId, onSelect, emptyText }) {
  if (items.length === 0) return <p className="px-4 py-10 text-center text-sm text-slate-500">{emptyText}</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {items.map((it) => {
        const active = it.id === selectedId;
        return (
          <li key={it.id}>
            <button type="button" onClick={() => onSelect(it.id)} aria-current={active ? 'true' : undefined}
              className={`block w-full border-l-[3px] px-4 py-3 text-left transition-colors ${active ? 'border-l-primary-600 bg-primary-50' : 'border-l-transparent hover:bg-slate-50'}`}>
              <span className="flex items-center gap-2 text-xs text-slate-500">
                <span className="font-medium text-slate-700">{t(typeMeta(it.type).label)}</span>
                <span className="inline-flex items-center gap-1.5"><i className={`h-2 w-2 rounded-full ${DOT[it.risk]}`} />{t(RISK[it.risk].label)}</span>
                {it.stale && it.status === 'PENDING' && <span className="font-medium text-amber-700">{t('Basi')}</span>}
              </span>
              <span className="mt-1 block text-sm font-semibold text-slate-900">{t(it.title)}</span>
              <span className="mt-0.5 flex items-center justify-between gap-2 text-xs text-slate-500">
                <span className="truncate">{it.supplier.name}</span>
                {it.status === 'PENDING' && (
                  <span className={`inline-flex shrink-0 items-center gap-1 ${isUrgent(it) ? 'font-semibold text-amber-700' : ''}`}>
                    <Icon name="clock" className="h-3 w-3" />{timeLeft(it.expires_at)}
                  </span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

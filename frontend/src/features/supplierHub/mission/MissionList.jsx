import Icon from '../../../components/common/Icon';
import StateBadge from '../StateBadge';
import { MISSION_STATUS, SCENARIO, dayTime, msLeft, timeLeft } from '../meta';
import { t } from '../../../i18n';

export function Progress({ value, total, className = '' }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  return (
    <span className={`block h-1.5 overflow-hidden rounded-full bg-slate-100 ${className}`} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={total}>
      <span className="block h-full rounded-full bg-primary-600" style={{ width: `${pct}%` }} />
    </span>
  );
}

export function ScenarioTile({ scenario, className = 'h-10 w-10' }) {
  return <span className={`flex shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-700 ${className}`} aria-hidden="true"><Icon name={SCENARIO[scenario]?.icon ?? 'flag'} className="h-5 w-5" /></span>;
}

// Baris misi: siapa yang sudah membalas dan kapan tenggatnya.
export default function MissionList({ missions, onOpen, emptyText }) {
  if (missions.length === 0) return <p className="px-4 py-10 text-center text-sm text-slate-500">{emptyText}</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {missions.map((m) => {
        const active = m.status === 'ACTIVE';
        const soon = active && msLeft(m.deadline) < 6 * 3600e3;
        return (
          <li key={m.id}>
            <button type="button" onClick={() => onOpen(m.id)} className="grid w-full gap-3 px-4 py-4 text-left transition-colors hover:bg-slate-50 sm:grid-cols-[minmax(0,1fr)_12rem_11rem] sm:items-center">
              <span className="flex min-w-0 items-start gap-3">
                <ScenarioTile scenario={m.scenario} />
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">#{m.number} {t(m.title)}</span>
                    <StateBadge meta={MISSION_STATUS[m.status]} />
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-slate-500">
                    {t(SCENARIO[m.scenario].label)} · {m.item}{m.po_number ? ` · ${m.po_number}` : ''} · oleh {m.created_by}
                  </span>
                </span>
              </span>
              <span>
                <span className="mb-1 block text-xs text-slate-600"><b className="tabular-nums text-slate-900">{m.replied}</b> dari {m.total} membalas</span>
                <Progress value={m.replied} total={m.total} />
              </span>
              <span className="text-xs text-slate-500 sm:text-right">
                <span className="block">Tenggat {dayTime(m.deadline)}</span>
                {active && <span className={`inline-flex items-center gap-1 ${soon ? 'font-semibold text-amber-700' : ''}`}><Icon name="clock" className="h-3 w-3" />Sisa {timeLeft(m.deadline)}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

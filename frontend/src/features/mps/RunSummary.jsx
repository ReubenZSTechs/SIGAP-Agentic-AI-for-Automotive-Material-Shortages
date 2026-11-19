import Badge from '../../components/common/Badge';
import { t } from '../../i18n';

const CARDS = [
  { key: 'n_critical', label: 'Critical', dot: 'bg-red-500', edge: 'border-l-red-500' },
  { key: 'n_warning', label: 'Warning', dot: 'bg-amber-500', edge: 'border-l-amber-500' },
  { key: 'n_safe', label: 'Aman', dot: 'bg-green-600', edge: 'border-l-green-600' },
];

export default function RunSummary({ run }) {
  return (
    <div className="mb-6 flex flex-wrap items-stretch gap-3">
      {CARDS.map((c) => (
        <div key={c.key} className={`min-w-[8.5rem] rounded-xl border border-l-4 border-slate-200 bg-white px-4 py-3 ${c.edge}`}>
          <div className="flex items-center gap-2 text-sm font-medium text-slate-600">
            <span className={`h-2 w-2 rounded-full ${c.dot}`} aria-hidden="true" />{t(c.label)}
          </div>
          <div className="mt-1 text-3xl font-bold leading-none tracking-tight text-slate-900 tabular-nums">{run[c.key] ?? 0}</div>
        </div>
      ))}
      <div className="ml-auto flex items-start gap-1.5">
        <Badge tone={run.status === 'PO_GENERATED' ? 'green' : 'slate'}>{run.status}</Badge>
        {run.is_stale && <Badge tone="amber">{t('Basi')}</Badge>}
      </div>
    </div>
  );
}

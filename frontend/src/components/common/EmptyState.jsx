import Icon from './Icon';
import { tx } from '../../i18n';

export function Spinner({ label = 'Memuat…' }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500" role="status">
      <svg className="h-4 w-4 animate-spin text-primary-600" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
        <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      </svg>
      {tx(label)}
    </div>
  );
}

export default function EmptyState({ title = 'Tidak ada data', description, action }) {
  return (
    <div className="flex flex-col items-center py-12 text-center">
      <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-500"><Icon name="box" className="h-5 w-5" /></span>
      <p className="font-semibold text-slate-800">{tx(title)}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{tx(description)}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

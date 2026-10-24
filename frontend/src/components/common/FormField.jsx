import { tx } from '../../i18n';

export default function FormField({ label, error, hint, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="mb-1.5 block text-sm font-medium text-slate-700">{tx(label)}</span>}
      {children}
      {hint && !error && <span className="mt-1.5 block text-xs text-slate-500">{tx(hint)}</span>}
      {error && <span role="alert" className="mt-1.5 block text-xs font-medium text-red-600">{tx(error)}</span>}
    </label>
  );
}

import { tx } from '../../i18n';

// variant 'underline' (tab halaman) | 'segmented' (toggle, mis. strategi sourcing)
export default function Tabs({ tabs, value, onChange, variant = 'underline' }) {
  if (variant === 'segmented') {
    return (
      <div className="inline-flex rounded-lg bg-slate-100 p-1" role="tablist">
        {tabs.map((tab) => (
          <button key={tab.id} role="tab" aria-selected={value === tab.id} disabled={tab.disabled}
            onClick={() => onChange(tab.id)}
            className={`rounded-md px-3 py-1 text-sm font-medium transition-colors disabled:opacity-40 ${
              value === tab.id ? 'bg-white text-primary-700 shadow-sm ring-1 ring-slate-200' : 'text-slate-600 hover:text-slate-900'}`}>
            {tx(tab.label)}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="mb-5 flex gap-6 border-b border-slate-200" role="tablist">
      {tabs.map((tab) => (
        <button key={tab.id} role="tab" aria-selected={value === tab.id} disabled={tab.disabled}
          onClick={() => onChange(tab.id)}
          className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-0.5 pb-3 pt-1 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            value === tab.id
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800'}`}>
          {tx(tab.label)}
        </button>
      ))}
    </div>
  );
}

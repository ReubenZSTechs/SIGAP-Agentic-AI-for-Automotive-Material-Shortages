import { tx } from '../../i18n';

const TONES = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  indigo: 'bg-primary-50 text-primary-700 ring-primary-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  green: 'bg-green-50 text-green-700 ring-green-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
};

export default function Badge({ tone = 'slate', children }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {tx(children)}
    </span>
  );
}

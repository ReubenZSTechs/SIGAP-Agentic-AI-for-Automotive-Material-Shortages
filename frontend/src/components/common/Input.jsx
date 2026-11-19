import { forwardRef } from 'react';

const base = `w-full h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm
  placeholder:text-slate-400 transition-colors hover:border-slate-400
  focus:border-primary-500 focus:outline-none focus:ring-3 focus:ring-primary-500/20
  disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 disabled:shadow-none`;

export default function Input({ className = '', ...rest }) {
  return <input className={`${base} ${className}`} {...rest} />;
}

export function Select({ className = '', children, ...rest }) {
  return <select className={`${base} ${className}`} {...rest}>{children}</select>;
}

export const Textarea = forwardRef(({ className = '', rows = 3, ...rest }, ref) => (
  <textarea ref={ref} rows={rows} className={`${base} h-auto py-2 ${className}`} {...rest} />
));

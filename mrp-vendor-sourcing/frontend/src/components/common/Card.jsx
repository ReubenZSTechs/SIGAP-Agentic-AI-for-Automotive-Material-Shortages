export default function Card({ title, actions, children, className = '', padded = true }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white ${padded ? '' : 'overflow-hidden'} ${className}`}>
      {(title || actions) && (
        <header className="flex min-h-12 items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={padded ? 'p-5' : ''}>{children}</div>
    </section>
  );
}

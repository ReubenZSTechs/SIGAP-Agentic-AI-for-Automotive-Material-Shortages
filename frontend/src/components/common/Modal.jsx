import { useEffect } from 'react';
import Icon from './Icon';

// Tutup dengan Esc / klik backdrop. `layer` untuk modal bertumpuk (mis. ConfirmDialog di atas modal lain).
export default function Modal({ open, title, onClose, footer, children, size = 'md', layer = 50 }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  const width = { md: 'max-w-md', lg: 'max-w-3xl', xl: 'max-w-5xl' }[size];

  return (
    <div className="fixed inset-0 flex items-center justify-center p-4" style={{ zIndex: layer }}
         role="dialog" aria-modal="true" aria-label={title}>
      <div className="anim-fade absolute inset-0 bg-primary-950/55" onClick={onClose} />
      <div className={`anim-pop relative flex max-h-[90vh] w-full flex-col rounded-2xl bg-white shadow-2xl ${width}`}>
        <header className="flex items-center justify-between gap-4 border-b border-slate-200 px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <button onClick={onClose} aria-label="Tutup dialog"
                  className="-mr-2 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700">
            <Icon name="x" className="h-5 w-5" />
          </button>
        </header>
        <div className="overflow-y-auto px-6 py-5">{children}</div>
        {footer && <footer className="flex justify-end gap-2 rounded-b-2xl border-t border-slate-200 bg-slate-50 px-6 py-3.5">{footer}</footer>}
      </div>
    </div>
  );
}

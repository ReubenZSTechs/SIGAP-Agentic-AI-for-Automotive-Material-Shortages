import { useToastStore } from '../../store/toastStore';
import Icon from './Icon';

const TONES = {
  success: { box: 'border-l-green-600', icon: 'check', color: 'text-green-600' },
  error: { box: 'border-l-red-600', icon: 'alert', color: 'text-red-600' },
  info: { box: 'border-l-primary-600', icon: 'info', color: 'text-primary-600' },
};

export default function Toaster() {
  const { toasts, dismiss } = useToastStore();
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => {
        const tone = TONES[t.tone] ?? TONES.info;
        return (
          <div key={t.id} role="status"
               className={`anim-slide pointer-events-auto flex items-start gap-3 rounded-lg border border-slate-200 border-l-4 bg-white px-3.5 py-3 text-sm text-slate-800 shadow-lg ${tone.box}`}>
            <Icon name={tone.icon} className={`mt-0.5 h-4 w-4 ${tone.color}`} />
            <span className="flex-1">{t.message}</span>
            <button onClick={() => dismiss(t.id)} aria-label="Tutup" className="text-slate-400 hover:text-slate-700"><Icon name="x" /></button>
          </div>
        );
      })}
    </div>
  );
}

import Icon from '../../../components/common/Icon';
import { MISSION_STEPS } from '../meta';
import { t } from '../../../i18n';

// Stepper bernomor karena alurnya berurutan: Rencana > Kirim > Kumpulkan > Rangkum > Ajukan.
export default function MissionStepper({ mission: m }) {
  const done = m.status === 'DONE';
  const sub = (i) => {
    const n = i + 1;
    if (done || n < m.step) return t('selesai');
    if (n > m.step) return t('menunggu');
    if (n === 2) return t('antre / draf menunggu review');
    if (n === 3) return t('{a} dari {b} balas', { a: m.replied, b: m.total });
    if (n === 4) return t('Agent merangkum…');
    return t('berjalan');
  };
  const cur = Math.min(m.step, MISSION_STEPS.length) - 1;
  return (
    <>
      <ol className="grid grid-cols-5 gap-1 sm:gap-2" aria-label={t('Tahap misi')}>
        {MISSION_STEPS.map((label, i) => {
          const n = i + 1;
          const state = done || n < m.step ? 'done' : n === m.step ? 'current' : 'todo';
          return (
            <li key={label} className="min-w-0" aria-current={state === 'current' ? 'step' : undefined}>
              <span className={`block h-1 rounded-full ${state === 'todo' ? 'bg-slate-200' : 'bg-primary-600'}`} />
              <span className="mt-2 flex items-center gap-1.5">
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                  state === 'done' ? 'bg-primary-600 text-white' : state === 'current' ? 'bg-white text-primary-700 ring-2 ring-primary-600' : 'bg-slate-100 text-slate-500'}`}>
                  {state === 'done' ? <Icon name="check" className="h-3 w-3" /> : n}
                </span>
                <span className={`hidden truncate text-sm font-semibold sm:inline ${state === 'todo' ? 'text-slate-500' : 'text-slate-900'}`}>{t(label)}</span>
              </span>
              <span className={`mt-0.5 hidden truncate pl-6.5 text-xs sm:block ${state === 'current' ? 'font-medium text-primary-700' : 'text-slate-500'}`}>{sub(i)}</span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-xs text-slate-600 sm:hidden">
        {done ? t('Semua tahap selesai') : <>{t('Tahap {n} dari 5:', { n: cur + 1 })} <b className="text-slate-900">{t(MISSION_STEPS[cur])}</b> · <span className="text-primary-700">{sub(cur)}</span></>}
      </p>
    </>
  );
}

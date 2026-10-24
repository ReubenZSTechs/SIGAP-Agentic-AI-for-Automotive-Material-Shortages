import Button from '../../components/common/Button';
import Icon from '../../components/common/Icon';
import { formatDate } from '../../utils/formatters';
import { t } from '../../i18n';

// Tampil bila run TERBARU basi: jadwal / PO / stok berubah setelah run dibuat. Tidak dihitung ulang otomatis.
export default function StaleRunBanner({ run, onRerun }) {
  if (!run?.is_stale) return null;
  return (
    <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 border-l-4 border-l-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <span className="flex items-start gap-2.5">
        <Icon name="alert" className="mt-0.5 h-4 w-4 text-amber-600" />
        <span>
          <b>Planning Run #{run.id}</b> ({formatDate(run.date_from)} – {formatDate(run.date_to)}) {t('sudah basi — jadwal, PO, atau stok berubah setelah run dibuat. Jalankan ulang agar angka defisit akurat.')}
        </span>
      </span>
      <Button size="sm" onClick={() => onRerun(run)}>{t('Jalankan Ulang')}</Button>
    </div>
  );
}

import Icon from '../../components/common/Icon';
import { useEffect, useState } from 'react';
import Button from '../../components/common/Button';
import Modal from '../../components/common/Modal';
import { Spinner } from '../../components/common/EmptyState';
import { scheduleService } from '../../services/scheduleService';
import { toast } from '../../store/toastStore';
import { formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

// Pratinjau dampak stok (dari GET /schedules/{id}/materials). Keputusan akhir tetap milik server:
// bila 409, dialog yang SAMA berganti menampilkan material yang kurang.
export default function StartProductionDialog({ open, schedule, materials, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [shortages, setShortages] = useState(null);
  useEffect(() => { if (open) setShortages(null); }, [open]);

  const start = async () => {
    setBusy(true);
    try {
      await scheduleService.setStatus(schedule.id, 'IN_PROGRESS');
      toast.success('Produksi dimulai — stok material dikurangi');
      onDone();
    } catch (e) {
      if (e.status === 409 && e.data?.shortages) setShortages(e.data.shortages);
      else toast.error(e.message);
    } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} size="lg" layer={60}
      title={t('Mulai Produksi · {batch}', { batch: schedule?.batch_code ?? '' })}
      footer={shortages ? <Button variant="secondary" onClick={onClose}>{t('Tutup')}</Button> : (
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button loading={busy} onClick={start}>{t('Mulai Produksi')}</Button>
        </>
      )}>
      {shortages ? (
        <div>
          <p className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
            <Icon name="alert" className="mt-0.5 h-4 w-4" /> Stok fisik tidak cukup — produksi belum dimulai dan tidak ada stok yang berubah.
          </p>
          <table className="w-full text-sm">
            <tbody>
              {shortages.map((s) => (
                <tr key={s.material_id} className="border-b border-slate-100">
                  <td className="py-1.5">{s.sku} · {s.name}</td>
                  <td className="py-1.5 text-right">butuh {formatQty(s.required)}, fisik {formatQty(s.on_hand)},
                    <b className="text-red-600"> kurang {formatQty(s.short_by)} {s.uom}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : !materials ? <Spinner /> : (
        <div>
          <p className="mb-3 text-sm text-slate-600">
            Material akan keluar dari stok fisik sekarang dan <b>{t('tidak dapat dibatalkan')}</b>.
          </p>
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="py-1 font-medium">{t('Material')}</th><th className="py-1 text-right font-medium">{t('Butuh')}</th>
                  <th className="py-1 text-right font-medium">{t('Stok fisik: sebelum ke sesudah')}</th></tr>
              </thead>
              <tbody>
                {materials.lines.map((l) => (
                  <tr key={l.material_id} className={`border-t border-slate-100 ${l.enough ? '' : 'text-red-600'}`}>
                    <td className="py-1.5">{l.name}</td>
                    <td className="py-1.5 text-right">{formatQty(l.required_qty)} {l.uom}</td>
                    <td className="py-1.5 text-right">{formatQty(l.on_hand)} <Icon name="arrowRight" className="mx-0.5 inline h-3.5 w-3.5 text-slate-400" /> <b>{formatQty(l.on_hand_after)}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            <Icon name="check" className="mr-1 inline h-3.5 w-3.5 text-green-600" />{t('Stok')} <i>{t('tersedia')}</i> tidak berubah: stok fisik dan stok terkunci turun sebesar kebutuhan batch.
          </p>
        </div>
      )}
    </Modal>
  );
}

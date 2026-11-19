import Icon from '../../components/common/Icon';
import { useState } from 'react';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import StatusBadge from '../../components/common/StatusBadge';
import { Spinner } from '../../components/common/EmptyState';
import StartProductionDialog from './StartProductionDialog';
import useFetch from '../../hooks/useFetch';
import { scheduleService } from '../../services/scheduleService';
import { toast } from '../../store/toastStore';
import { SCHEDULE_ACTIONS, SCHEDULE_STATUS } from '../../utils/constants';
import { formatDate, formatDateTime, formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

function Row({ label, children }) {
  return <div className="flex justify-between gap-3 py-0.5"><dt className="text-slate-500">{label}</dt><dd className="text-right">{children}</dd></div>;
}

// Side-panel batch: info, aksi status (sesuai transisi valid dari server), dan alokasi material.
export default function ScheduleDrawer({ schedule: s, onClose, onChanged, onEdit }) {
  const mats = useFetch(() => scheduleService.materials(s.id),
    [s.id, s.status, s.production_date, s.target_qty, s.product_id]);
  const [dialog, setDialog] = useState(null); // 'IN_PROGRESS' | 'CANCELLED' | null
  const [busy, setBusy] = useState(false);
  const st = SCHEDULE_STATUS[s.status];

  const apply = async (status) => {
    setBusy(true);
    try {
      await scheduleService.setStatus(s.id, status);
      toast.success(`Status: ${t(SCHEDULE_STATUS[status].label)}`);
      setDialog(null);
      onChanged();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <aside aria-label={t('Detail batch')} className="anim-slide fixed inset-y-0 right-0 z-40 w-full max-w-[440px] overflow-y-auto border-l border-slate-200 bg-white p-5 shadow-2xl">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-mono text-sm font-semibold text-slate-900">{s.batch_code}</h2>
          <Badge tone={st.tone}>{t(st.label)}</Badge>
        </div>
        <button onClick={onClose} aria-label={t('Tutup panel')} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="x" className="h-5 w-5" /></button>
      </header>

      <dl className="my-3 text-sm">
        <Row label={t('Produk')}>{s.product_name} <span className="font-mono text-xs text-slate-500">({s.product_sku})</span></Row>
        <Row label={t('Quantity')}>{formatQty(s.target_qty)} unit</Row>
        <Row label={t('Production line')}>{s.line_code} · {s.line_name}</Row>
        <Row label={t('Tanggal produksi')}>{formatDate(s.production_date)}</Row>
        {s.started_at && <Row label={t('Mulai')}>{formatDateTime(s.started_at)}</Row>}
        {s.completed_at && <Row label={t('Selesai')}>{formatDateTime(s.completed_at)}</Row>}
      </dl>

      <div className="flex flex-wrap gap-2">
        {s.allowed_transitions.map((item) => ( // aturan transisi dari server; tidak diduplikasi di klien
          <Button key={item} variant={SCHEDULE_ACTIONS[item].variant} loading={busy && !dialog}
                  onClick={() => (item === 'COMPLETED' ? apply(item) : setDialog(item))}>
            {t(SCHEDULE_ACTIONS[item].label)}
          </Button>
        ))}
        {s.editable && <Button variant="secondary" onClick={() => onEdit(s)}>{t('Edit')}</Button>}
      </div>

      <h3 className="mb-2 mt-6 border-t border-slate-200 pt-4 text-sm font-semibold text-slate-900">{t('Alokasi Material')}</h3>
      {mats.loading ? <Spinner /> : mats.error ? (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{mats.error.message}</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="py-1 font-medium">{t('Material')}</th><th className="py-1 text-right font-medium">{t('Butuh')}</th>
              <th className="py-1 text-right font-medium">{t('Fisik')}</th><th className="py-1 text-right font-medium">{t('Tersedia')}</th>
              <th className="py-1 pl-2 font-medium">{t('Status')}</th></tr>
          </thead>
          <tbody>
            {mats.data.lines.map((l) => (
              <tr key={l.material_id} className="border-t border-slate-100">
                <td className="py-1.5"><span className="font-mono text-xs text-slate-500">{l.sku}</span><br />{l.name}</td>
                <td className="py-1.5 text-right">{formatQty(l.required_qty)} {l.uom}</td>
                <td className="py-1.5 text-right">{formatQty(l.on_hand)}</td>
                <td className={`py-1.5 text-right ${l.available < 0 ? 'text-red-600' : ''}`}>{formatQty(l.available)}</td>
                <td className="py-1.5 pl-2"><StatusBadge status={l.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-xs text-slate-500">
        {t('Status stok adalah kondisi')} <b>{t('global')}</b> {t('material (semua jadwal PLANNED), bukan khusus batch ini.')}
      </p>

      <StartProductionDialog open={dialog === 'IN_PROGRESS'} schedule={s} materials={mats.data}
        onClose={() => setDialog(null)} onDone={() => { setDialog(null); onChanged(); }} />
      <ConfirmDialog open={dialog === 'CANCELLED'} loading={busy} confirmLabel={t('Ya, batalkan')}
        message={t('Batalkan {batch}? Stok terkunci untuk batch ini dilepas.', { batch: s.batch_code })}
        onConfirm={() => apply('CANCELLED')} onCancel={() => setDialog(null)} />
    </aside>
  );
}

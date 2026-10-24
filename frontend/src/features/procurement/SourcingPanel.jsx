import Icon from '../../components/common/Icon';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Button from '../../components/common/Button';
import EmptyState, { Spinner } from '../../components/common/EmptyState';
import Tabs from '../../components/common/Tabs';
import SourcingCard from './SourcingCard';
import { usePlanningStore } from '../../store/planningStore';
import { STRATEGIES } from '../../utils/constants';
import { formatRupiah } from '../../utils/formatters';
import { t } from '../../i18n';

export default function SourcingPanel({ onNext }) {
  const { run, sourcing, strategy, setStrategy, loadSourcing, select, clearSelection, autoSelect } = usePlanningStore();
  const [loading, setLoading] = useState(true);
  const [auto, setAuto] = useState(false);
  const locked = run.status === 'PO_GENERATED';

  useEffect(() => {
    setLoading(true);
    loadSourcing().finally(() => setLoading(false));
  }, [run.id, loadSourcing]);

  // Ringkasan footer dihitung di klien dari state (server tetap sumber kebenaran).
  const summary = useMemo(() => {
    const picked = sourcing.filter((it) => it.line.selected_supplier_id != null);
    return {
      total: sourcing.length,
      selected: picked.length,
      suppliers: new Set(picked.map((it) => it.line.selected_supplier_id)).size,
      amount: picked.reduce((a, it) => a + (it.line.order_qty ?? 0) * (it.line.unit_price ?? 0), 0),
    };
  }, [sourcing]);
  const complete = summary.total > 0 && summary.selected === summary.total;

  const changeStrategy = async (s) => { setLoading(true); await setStrategy(s); setLoading(false); };
  const runAuto = async () => { setAuto(true); await autoSelect(); setAuto(false); };

  return (
    <div className="space-y-4">
      {locked && (
        <p className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          {t('PO sudah dibuat untuk run ini — pilihan supplier terkunci.')}{' '}
          <Link className="font-medium underline" to="/purchase-orders">{t('Lihat daftar PO')}</Link>
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">{t('Strategi:')}</span>
          <Tabs variant="segmented" value={strategy} onChange={changeStrategy}
                tabs={STRATEGIES.map((s) => ({ id: s.id, label: s.label }))} />
        </div>
        <Button variant="secondary" loading={auto} disabled={locked} onClick={runAuto}><Icon name="spark" /> {t('Pilih Otomatis')}</Button>
      </div>

      {loading && sourcing.length === 0 ? <Spinner /> : (
        sourcing.length === 0
          ? <EmptyState title={t('Tidak ada material defisit')} />
          : sourcing.map((it) => (
            <SourcingCard key={it.line.id} item={it} locked={locked} onSelect={select} onClear={clearSelection} />
          ))
      )}

      <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <span className="text-sm text-slate-600">
          {t('Terpilih')} <b>{summary.selected} / {summary.total}</b> {t('material')} · {summary.suppliers} supplier ·{' '}
          {t('Estimasi')} <b>{formatRupiah(summary.amount)}</b>
        </span>
        <Button disabled={!complete} onClick={onNext}>{t('Buat Purchase Order')} <Icon name="arrowRight" /></Button>
      </div>
    </div>
  );
}

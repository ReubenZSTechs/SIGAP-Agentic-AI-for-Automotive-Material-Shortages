import Icon from '../../components/common/Icon';
import { useMemo, useState } from 'react';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import DataTable from '../../components/common/DataTable';
import StatusBadge from '../../components/common/StatusBadge';
import Tabs from '../../components/common/Tabs';
import { formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

export default function PlanningResultTable({ lines, onNext }) {
  const [filter, setFilter] = useState('action'); // action | all
  const hasDeficit = lines.some((l) => l.shortfall > 0);
  const rows = useMemo(
    () => (filter === 'action' ? lines.filter((l) => l.status !== 'SAFE') : lines), [lines, filter]);

  const columns = [
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'material_name', header: 'Material' },
    { key: 'gross_requirement', header: 'Kebutuhan', align: 'right',
      render: (l) => `${formatQty(l.gross_requirement)} ${l.uom}` },
    { key: 'on_hand', header: 'Fisik', align: 'right', render: (l) => formatQty(l.on_hand) },
    { key: 'allocated', header: 'Terkunci', align: 'right', render: (l) => formatQty(l.allocated) },
    { key: 'available', header: 'Tersedia', align: 'right', render: (l) => (
      <div>
        <span className={l.available < 0 ? 'font-medium text-red-600' : ''}>{formatQty(l.available)}</span>
        {l.on_order > 0 && <div className="text-xs text-slate-500">{t('+{qty} dipesan', { qty: formatQty(l.on_order) })}</div>}
      </div>
    ) },
    { key: 'safety_stock', header: 'Safety', align: 'right', render: (l) => formatQty(l.safety_stock) },
    { key: 'shortfall', header: 'Defisit', align: 'right', render: (l) => (
      <span className={l.shortfall > 0 ? 'font-semibold text-slate-900' : 'text-slate-400'}>{formatQty(l.shortfall)}</span>
    ) },
    { key: 'status', header: 'Status', render: (l) => <StatusBadge status={l.status} /> },
  ];

  return (
    <div className="space-y-3">
      {!hasDeficit && (
        <p className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          {t('Semua stok aman — tidak ada defisit, tidak perlu pembelian tambahan.')}
        </p>
      )}
      <div className="flex items-center gap-2">
        <span className="text-sm text-slate-500">{t('Filter:')}</span>
        <Tabs variant="segmented" value={filter} onChange={setFilter}
              tabs={[{ id: 'action', label: 'Perlu tindakan' }, { id: 'all', label: 'Semua' }]} />
      </div>
      <Card padded={false}>
        <DataTable columns={columns} rows={rows} emptyText={t('Tidak ada material yang perlu tindakan')} />
      </Card>
      <div className="flex justify-end">
        <Button disabled={!hasDeficit} onClick={onNext}>{t('Lanjut ke Sourcing')} <Icon name="arrowRight" /></Button>
      </div>
    </div>
  );
}

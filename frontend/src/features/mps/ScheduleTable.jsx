import DataTable from '../../components/common/DataTable';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import { SCHEDULE_STATUS } from '../../utils/constants';
import { formatDate, formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

export default function ScheduleTable({ rows, loading, onDetail, onEdit }) {
  const columns = [
    { key: 'batch_code', header: 'Batch', className: 'font-mono text-xs' },
    { key: 'production_date', header: 'Tanggal', render: (r) => formatDate(r.production_date) },
    { key: 'product_name', header: 'Produk' },
    { key: 'target_qty', header: 'Qty', align: 'right', render: (r) => formatQty(r.target_qty) },
    { key: 'line_code', header: 'Line' },
    { key: 'status', header: 'Status', render: (r) => {
      const s = SCHEDULE_STATUS[r.status] ?? { label: r.status, tone: 'slate' };
      return <Badge tone={s.tone}>{t(s.label)}</Badge>;
    } },
    { key: 'actions', header: 'Aksi', align: 'right', render: (r) => (
      <span className="inline-flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => onDetail(r)}>{t('Detail')}</Button>
        {r.editable && <Button size="sm" variant="ghost" onClick={() => onEdit(r)}>{t('Edit')}</Button>}
      </span>
    ) },
  ];
  return <DataTable columns={columns} rows={rows} loading={loading} emptyText={t('Belum ada jadwal produksi')}
                    rowClassName={(r) => (r.status === 'CANCELLED' ? 'text-slate-400' : '')} />;
}

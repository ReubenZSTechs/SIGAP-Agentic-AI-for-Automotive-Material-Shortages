import DataTable from '../../components/common/DataTable';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import { t } from '../../i18n';

export default function MaterialTable({ rows, loading, onSuppliers, onEdit, onDelete }) {
  const columns = [
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'name', header: 'Nama', render: (r) => (
      <span className={r.is_active ? '' : 'text-slate-400 line-through'}>{r.name}</span>
    ) },
    { key: 'uom', header: 'Satuan' },
    { key: 'is_active', header: 'Status', render: (r) => (
      <Badge tone={r.is_active ? 'green' : 'slate'}>{r.is_active ? 'Aktif' : 'Nonaktif'}</Badge>
    ) },
    { key: 'actions', header: 'Aksi', align: 'right', render: (r) => (
      <span className="inline-flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => onSuppliers(r)}>{t('Supplier')}</Button>
        <Button size="sm" variant="ghost" onClick={() => onEdit(r)}>{t('Edit')}</Button>
        <Button size="sm" variant="ghost" className="text-red-600" onClick={() => onDelete(r)}>{t('Hapus')}</Button>
      </span>
    ) },
  ];
  return <DataTable columns={columns} rows={rows} loading={loading} emptyText={t('Belum ada material beli')} />;
}

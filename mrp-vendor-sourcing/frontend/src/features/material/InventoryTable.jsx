import DataTable from '../../components/common/DataTable';
import StatusBadge from '../../components/common/StatusBadge';
import Button from '../../components/common/Button';
import StockLevel from './StockLevel';
import { formatQty } from '../../utils/formatters';

export default function InventoryTable({ rows, loading, onEdit, onHistory }) {
  const columns = [
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'name', header: 'Material' },
    { key: 'uom', header: 'Satuan' },
    { key: 'on_hand', header: 'Stok Fisik', align: 'right', render: (r) => formatQty(r.on_hand) },
    { key: 'allocated', header: 'Terkunci', align: 'right', render: (r) => formatQty(r.allocated) },
    { key: 'available', header: 'Tersedia', align: 'right', render: (r) => (
      <span className={r.available < 0 ? 'font-medium text-red-600' : ''}>{formatQty(r.available)}</span>
    ) },
    { key: 'safety_stock', header: 'Safety', align: 'right', render: (r) => formatQty(r.safety_stock) },
    { key: 'on_order', header: 'Dipesan', align: 'right', render: (r) => (
      r.on_order > 0 ? <span className="text-indigo-700">+{formatQty(r.on_order)}</span> : <span className="text-slate-300">0</span>
    ) },
    { key: 'level', header: 'Tingkat stok', render: (r) => <StockLevel row={r} /> },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'actions', header: '', align: 'right', render: (r) => (
      <span className="inline-flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => onHistory(r)}>Riwayat</Button>
        <Button size="sm" variant="ghost" onClick={() => onEdit(r)}>Edit</Button>
      </span>
    ) },
  ];
  return <DataTable columns={columns} rows={rows} loading={loading} rowKey="material_id"
                    emptyText="Belum ada data stok" />;
}

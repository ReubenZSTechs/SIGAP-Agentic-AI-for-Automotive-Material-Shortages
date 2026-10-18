import { useNavigate } from 'react-router-dom';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import DataTable from '../../components/common/DataTable';
import { formatRupiah } from '../../utils/formatters';

export default function ProductTable({ rows, loading, onEdit, onDelete }) {
  const navigate = useNavigate();
  const columns = [
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'name', header: 'Nama Produk', render: (r) => (
      <span className={r.is_active ? 'font-medium' : 'text-slate-400 line-through'}>{r.name}</span>
    ) },
    { key: 'uom', header: 'Satuan' },
    { key: 'selling_price', header: 'Harga Jual', align: 'right', render: (r) => formatRupiah(r.selling_price) },
    { key: 'specification', header: 'Spesifikasi', className: 'max-w-xs', render: (r) => (
      r.specification
        ? <span className="block truncate text-slate-600" title={r.specification}>{r.specification}</span>
        : <span className="text-slate-400">—</span>
    ) },
    { key: 'bom', header: 'BOM', render: (r) => (
      r.bom_item_count > 0
        ? <Badge tone="green">{r.bom_item_count} komponen</Badge>
        : <Badge tone="amber">Belum ada BOM</Badge>
    ) },
    { key: 'is_active', header: 'Status', render: (r) => (
      <Badge tone={r.is_active ? 'green' : 'slate'}>{r.is_active ? 'Aktif' : 'Nonaktif'}</Badge>
    ) },
    { key: 'actions', header: 'Aksi', align: 'right', render: (r) => (
      <span className="inline-flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => navigate(`/bom?product=${r.id}`)}>BOM</Button>
        <Button size="sm" variant="ghost" onClick={() => onEdit(r)}>Edit</Button>
        <Button size="sm" variant="ghost" className="text-red-600" onClick={() => onDelete(r)}>Hapus</Button>
      </span>
    ) },
  ];
  return <DataTable columns={columns} rows={rows} loading={loading}
                    emptyText="Belum ada produk final — klik + Tambah Produk" />;
}

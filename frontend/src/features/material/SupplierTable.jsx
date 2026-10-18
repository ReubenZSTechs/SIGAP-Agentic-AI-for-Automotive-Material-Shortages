import DataTable from '../../components/common/DataTable';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';

export default function SupplierTable({ rows, loading, onEdit, onDelete }) {
  const columns = [
    { key: 'code', header: 'Kode', className: 'font-mono text-xs' },
    { key: 'name', header: 'Nama' },
    { key: 'contact', header: 'Kontak', render: (r) => r.contact || '—' },
    { key: 'payment_term_days', header: 'Termin', render: (r) => (r.payment_term_days > 0 ? `Net ${r.payment_term_days}` : 'Tunai') },
    { key: 'is_active', header: 'Status', render: (r) => (
      <Badge tone={r.is_active ? 'green' : 'slate'}>{r.is_active ? 'Aktif' : 'Nonaktif'}</Badge>
    ) },
    { key: 'actions', header: 'Aksi', align: 'right', render: (r) => (
      <span className="inline-flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => onEdit(r)}>Edit</Button>
        <Button size="sm" variant="ghost" className="text-red-600" onClick={() => onDelete(r)}>Hapus</Button>
      </span>
    ) },
  ];
  return <DataTable columns={columns} rows={rows} loading={loading} emptyText="Belum ada supplier" />;
}

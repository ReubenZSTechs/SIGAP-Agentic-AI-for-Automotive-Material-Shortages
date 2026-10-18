import Card from '../../components/common/Card';
import DataTable from '../../components/common/DataTable';
import StatusBadge from '../../components/common/StatusBadge';
import { formatQty } from '../../utils/formatters';

// Cermin tabel Phase 5 dokumen alur. Terkunci = Fisik Baru − Tersedia.
export default function ReceiptResultTable({ changes, items }) {
  const nameOf = (c) => items.find((i) => i.material_id === c.material_id)?.name ?? c.sku;
  const columns = [
    { key: 'material', header: 'Material', render: (c) => nameOf(c) },
    { key: 'old_on_hand', header: 'Fisik Lama', align: 'right', render: (c) => formatQty(c.old_on_hand) },
    { key: 'received', header: 'Masuk', align: 'right', render: (c) => `+${formatQty(c.received)}` },
    { key: 'new_on_hand', header: 'Fisik Baru', align: 'right', render: (c) => formatQty(c.new_on_hand) },
    { key: 'locked', header: 'Terkunci', align: 'right', render: (c) => formatQty(c.new_on_hand - c.available) },
    { key: 'available', header: 'Tersedia', align: 'right', render: (c) => formatQty(c.available) },
    { key: 'status', header: 'Status', render: (c) => <StatusBadge status={c.status} /> },
  ];
  return (
    <Card title="Hasil Penerimaan — Pembaruan Stok" padded={false}>
      <DataTable columns={columns} rows={changes} rowKey="material_id" />
    </Card>
  );
}

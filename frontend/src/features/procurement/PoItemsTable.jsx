import Card from '../../components/common/Card';
import DataTable from '../../components/common/DataTable';
import { formatDate, formatQty, formatRupiah } from '../../utils/formatters';
import { t } from '../../i18n';

export default function PoItemsTable({ items }) {
  const columns = [
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'name', header: 'Material' },
    { key: 'qty_ordered', header: 'Dipesan', align: 'right', render: (i) => `${formatQty(i.qty_ordered)} ${i.uom}` },
    { key: 'unit_price', header: 'Harga/Unit', align: 'right', render: (i) => formatRupiah(i.unit_price) },
    { key: 'line_total', header: 'Subtotal', align: 'right', render: (i) => formatRupiah(i.line_total) },
    { key: 'needed_by_date', header: 'Dibutuhkan', render: (i) => (i.needed_by_date ? formatDate(i.needed_by_date) : '—') },
    { key: 'qty_received', header: 'Diterima', align: 'right', render: (i) => formatQty(i.qty_received) },
  ];
  return <Card title={t('Item PO')} padded={false}><DataTable columns={columns} rows={items} /></Card>;
}

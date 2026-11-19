import { useNavigate } from 'react-router-dom';
import DataTable from '../../components/common/DataTable';
import Badge from '../../components/common/Badge';
import PoStatusBadge from '../../components/common/PoStatusBadge';
import { PO_SOURCE } from '../../utils/constants';
import { formatDate, formatRupiah } from '../../utils/formatters';
import { t } from '../../i18n';

export default function PoTable({ rows, loading, emptyText = 'Belum ada Purchase Order' }) {
  const navigate = useNavigate();
  const columns = [
    { key: 'po_number', header: 'No. PO', className: 'font-mono text-xs' },
    { key: 'supplier_name', header: 'Supplier' },
    { key: 'source', header: 'Sumber', render: (r) => {
      const s = PO_SOURCE[r.source] ?? PO_SOURCE.PLANNING;
      return <Badge tone={s.tone}>{t(s.label)}</Badge>;
    } },
    { key: 'created_at', header: 'Tanggal', render: (r) => formatDate(r.po_date ?? r.created_at) },
    { key: 'total_amount', header: 'Total', align: 'right', render: (r) => formatRupiah(r.total_amount) },
    { key: 'status', header: 'Status', render: (r) => <PoStatusBadge status={r.status} /> },
  ];
  return <DataTable columns={columns} rows={rows} loading={loading} emptyText={emptyText}
                    onRowClick={(r) => navigate(`/purchase-orders/${r.id}`)} />;
}

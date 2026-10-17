import { useNavigate } from 'react-router-dom';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import DataTable from '../../components/common/DataTable';
import { formatDate } from '../../utils/formatters';

export default function PlanningRunList({ runs, loading }) {
  const navigate = useNavigate();
  const columns = [
    { key: 'id', header: 'Run', render: (r) => <span className="font-medium">#{r.id}</span> },
    { key: 'range', header: 'Rentang', render: (r) => `${formatDate(r.date_from)} – ${formatDate(r.date_to)}` },
    { key: 'summary', header: 'Ringkasan', render: (r) => (
      <span className="inline-flex gap-4 text-sm" aria-label="Critical, Warning, Aman">
        <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-red-500" />{r.n_critical}</span><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-amber-500" />{r.n_warning}</span><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-green-600" />{r.n_safe}</span>
      </span>
    ) },
    { key: 'status', header: 'Status', render: (r) => (
      <span className="inline-flex gap-1">
        <Badge tone={r.status === 'PO_GENERATED' ? 'green' : 'slate'}>{r.status}</Badge>
        {r.is_stale && <Badge tone="amber">Basi</Badge>}
      </span>
    ) },
    { key: 'actions', header: '', align: 'right', render: (r) => (
      <Button size="sm" variant="secondary" onClick={() => navigate(`/planning/${r.id}`)}>Buka</Button>
    ) },
  ];
  return <DataTable columns={columns} rows={runs} loading={loading} emptyText="Belum ada planning run" />;
}

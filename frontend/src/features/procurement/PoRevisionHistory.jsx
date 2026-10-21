import Badge from '../../components/common/Badge';
import Card from '../../components/common/Card';
import Icon from '../../components/common/Icon';
import useFetch from '../../hooks/useFetch';
import { purchaseOrderService } from '../../services/purchaseOrderService';
import { formatDateTime, formatRupiah } from '../../utils/formatters';

const STATUS = { CURRENT: { label: 'Sedang dibahas', tone: 'indigo' }, SUPERSEDED: { label: 'Digantikan', tone: 'slate' }, FINAL: { label: 'Final', tone: 'green' } };

// Versi PO yang dibahas dengan supplier via Telegram: v1 = yang pertama dikirim, v2+ = revisi yang disetujui
// manajer, FINAL = dikonfirmasi supplier tanpa perubahan lagi (PDF-nya dikirim ke supplier).
export default function PoRevisionHistory({ po }) {
  const signature = `${po.status}-${po.total_amount}`;
  const { data } = useFetch(() => purchaseOrderService.revisions(po.id), [po.id, signature]);
  if (!data?.length) return null;
  const final = data.find((r) => r.status === 'FINAL');

  return (
    <Card title="Riwayat versi PO" actions={final && <Badge tone="green">Final dikonfirmasi · v{final.version}</Badge>}>
      <ol className="space-y-3">
        {[...data].reverse().map((r) => (
          <li key={r.id} className="rounded-lg border border-slate-200 px-3.5 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-slate-900">Versi {r.version}</b>
              <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
              <span className="tabular-nums text-slate-600">{formatRupiah(r.total_amount)}</span>
              <span className="text-xs text-slate-500">
                {r.version === 1 ? 'dikirim ke supplier' : `revisi disetujui${r.created_by ? ` oleh ${r.created_by}` : ''}`} · {formatDateTime(r.created_at)}
                {r.finalized_at && ` · dikonfirmasi ${formatDateTime(r.finalized_at)}`}
              </span>
              <a href={purchaseOrderService.revisionPdfUrl(po.id, r.id)} target="_blank" rel="noreferrer"
                className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline">
                <Icon name="download" className="h-3.5 w-3.5" /> PDF{r.pdf_sent ? ' (terkirim)' : ''}
              </a>
            </div>
            {r.changes.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-slate-700">
                {r.changes.map((c) => <li key={`${c.po_item_id}-${c.field}`}>{c.text}</li>)}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}

import { Link, useNavigate } from 'react-router-dom';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import Icon from '../../components/common/Icon';
import StateBadge from './StateBadge';
import { DECISION, MISSION_STATUS, SCENARIO, dayTime } from './meta';
import useFetch from '../../hooks/useFetch';
import { hubService } from '../../services/hubService';
import { formatDate } from '../../utils/formatters';

const CONF = { PENDING: 'Menunggu konfirmasi supplier', CONFIRMED: 'Dikonfirmasi supplier', DECLINED: 'Ditolak supplier',
  CANCEL_PENDING: 'Menunggu persetujuan pembatalan', REVISION_PENDING: 'Supplier minta revisi' };
const CONV = { CONFIRM_ORDER: 'Konfirmasi PO', CANCEL_ORDER: 'Pembatalan PO', REVISION_CONFIRM: 'Konfirmasi revisi' };
const CONV_STATUS = { QUEUED: 'antre', AWAITING_SUPPLIER: 'menunggu supplier', REVISION_REQUESTED: 'menunggu keputusan revisi',
  CONFIRMED: 'dikonfirmasi', CANCEL_CONFIRMED: 'pembatalan disetujui', DECLINED: 'ditolak supplier', ESCALATED: 'dieskalasi', CLOSED: 'selesai' };

// Panel read-only di detail PO: konfirmasi supplier, percakapan Telegram, misi Hub, dan ajuan terkait.
// Data PO dipakai untuk membuat misi; misi tidak pernah mengubah PO.
export default function PoHubPanel({ po }) {
  const navigate = useNavigate();
  const { data, error } = useFetch(() => hubService.poContext(po.id), [po.id, po.status]);
  const canMission = po.status !== 'CANCELLED';

  return (
    <Card title="Misi & komunikasi supplier" actions={canMission && (
      <Button size="sm" variant="secondary" onClick={() => navigate(`/supplier-hub/missions?new=1&po=${po.id}`)}><Icon name="flag" /> Buat misi dari PO ini</Button>
    )}>
      {error ? <p className="text-sm text-slate-500">Data Agent Hub tidak tersedia ({error.message}).</p> : !data ? <p className="text-sm text-slate-500">Memuat…</p> : (
        <div className="space-y-4 text-sm">
          {data.confirmation && (
            <p className="flex flex-wrap items-center gap-x-2 text-slate-700">
              <Icon name="send" className="h-4 w-4 text-slate-500" />{CONF[data.confirmation.status] ?? data.confirmation.status}
              {data.confirmation.promised_delivery_date && <span>· janji kirim <b>{formatDate(data.confirmation.promised_delivery_date)}</b></span>}
              {data.confirmation.supplier_reference && <span className="font-mono text-xs text-slate-500">· ref {data.confirmation.supplier_reference}</span>}
            </p>
          )}
          {data.conversations.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-500">Percakapan Telegram</h3>
              <ul className="space-y-1">
                {data.conversations.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-center justify-between gap-2">
                    <span>{CONV[c.purpose] ?? c.purpose} · <span className="text-slate-500">{CONV_STATUS[c.status] ?? c.status}</span> · <span className="text-xs text-slate-500">{dayTime(c.last_activity_at)}</span></span>
                    <Link className="text-xs font-medium text-primary-700 hover:underline" to={`/supplier-hub/conversations/${c.supplier_id}`}>Buka thread</Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.missions.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-500">Misi Agent Hub</h3>
              <ul className="space-y-1.5">
                {data.missions.map((m) => (
                  <li key={m.id}>
                    <Link to={`/supplier-hub/missions/${m.id}`} className="flex flex-wrap items-center gap-2 font-medium text-primary-700 hover:underline">
                      Misi #{m.number} · {SCENARIO[m.scenario]?.label} <StateBadge meta={MISSION_STATUS[m.status]} />
                    </Link>
                    {m.summary && <p className="text-xs text-slate-500">{m.summary}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.approvals.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-500">Ajuan terkait</h3>
              <ul className="space-y-1">
                {data.approvals.map((a) => (
                  <li key={a.id}><Link to={`/supplier-hub?item=${a.id}`} className="inline-flex items-center gap-2 text-primary-700 hover:underline">{a.title} <StateBadge meta={DECISION[a.status] ?? DECISION.PENDING} /></Link></li>
                ))}
              </ul>
            </div>
          )}
          {!data.confirmation && !data.conversations.length && !data.missions.length && !data.approvals.length && (
            <p className="text-slate-500">Belum ada komunikasi supplier untuk PO ini. Buat misi untuk menanyakan harga, stok, jadwal kirim, atau dokumen.</p>
          )}
        </div>
      )}
    </Card>
  );
}

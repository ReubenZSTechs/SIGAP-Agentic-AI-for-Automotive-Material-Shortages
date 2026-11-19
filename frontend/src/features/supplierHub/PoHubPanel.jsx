import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import Icon from '../../components/common/Icon';
import StateBadge from './StateBadge';
import { DECISION, MISSION_STATUS, SCENARIO, approverName, dayTime } from './meta';
import useFetch from '../../hooks/useFetch';
import { hubService } from '../../services/hubService';
import { toast } from '../../store/toastStore';
import { formatDate } from '../../utils/formatters';
import { t } from '../../i18n';

const CONF = { PENDING: 'Menunggu konfirmasi supplier', CONFIRMED: 'Dikonfirmasi supplier', DECLINED: 'Ditolak supplier',
  CANCEL_PENDING: 'Menunggu persetujuan pembatalan', REVISION_PENDING: 'Supplier minta revisi' };
const CONV = { CONFIRM_ORDER: 'Konfirmasi PO', CANCEL_ORDER: 'Pembatalan PO', REVISION_CONFIRM: 'Konfirmasi revisi' };
const OPEN_CONV = ['QUEUED', 'AWAITING_SUPPLIER', 'REVISION_REQUESTED'];
const CONV_STATUS = { QUEUED: 'antre', AWAITING_SUPPLIER: 'menunggu supplier', REVISION_REQUESTED: 'menunggu keputusan revisi',
  CONFIRMED: 'dikonfirmasi', CANCEL_CONFIRMED: 'pembatalan disetujui', DECLINED: 'ditolak supplier', ESCALATED: 'dieskalasi', CLOSED: 'selesai' };

// Panel di detail PO: konfirmasi supplier, percakapan Telegram, misi Hub, dan ajuan terkait. PO ISSUED dikirim
// otomatis ke supplier; tombol di sini mengirim ulang (mis. setelah eskalasi) atau meminta persetujuan pembatalan.
export default function PoHubPanel({ po, onChanged }) {
  const navigate = useNavigate();
  const lines = po.items.map((i) => `${i.qty_ordered}x${i.unit_price}`).join(',');
  const { data, error, reload } = useFetch(() => hubService.poContext(po.id), [po.id, po.status, po.total_amount, lines]);
  const [busy, setBusy] = useState(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const canMission = po.status !== 'CANCELLED';
  const open = (data?.conversations ?? []).some((c) => OPEN_CONV.includes(c.status));
  const canSend = po.status === 'ISSUED' && data && !open && data.confirmation?.status !== 'CONFIRMED'; // kirim ulang setelah ditolak/eskalasi
  const cancelPending = (data?.conversations ?? []).some((c) => c.purpose === 'CANCEL_ORDER' && OPEN_CONV.includes(c.status));

  const start = async (purpose) => {
    setBusy(purpose);
    try {
      await hubService.startSupplierConversation(po.id, purpose, approverName());
      toast.success(purpose === 'CONFIRM_ORDER' ? t('PO dikirim ke supplier via Telegram') : t('Permintaan pembatalan dikirim ke supplier'));
      reload(); onChanged?.();
    } catch (e) { toast.error(e.message); } finally { setBusy(null); setConfirmCancel(false); }
  };

  return (
    <Card title={t('Misi & komunikasi supplier')} actions={canMission && (
      <span className="inline-flex flex-wrap gap-2">
        {canSend && <Button size="sm" variant="secondary" loading={busy === 'CONFIRM_ORDER'} onClick={() => start('CONFIRM_ORDER')}><Icon name="send" /> {t('Kirim ke supplier')}</Button>}
        {po.status === 'ISSUED' && data && !cancelPending && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => setConfirmCancel(true)}>{t('Minta pembatalan')}</Button>}
        <Button size="sm" variant="secondary" onClick={() => navigate(`/supplier-hub/missions?new=1&po=${po.id}`)}><Icon name="flag" /> {t('Buat misi dari PO ini')}</Button>
      </span>
    )}>
      {error ? <p className="text-sm text-slate-500">{t('Data Agent Hub tidak tersedia ({msg}).', { msg: error.message })}</p> : !data ? <p className="text-sm text-slate-500">{t('Memuat…')}</p> : (
        <div className="space-y-4 text-sm">
          {data.confirmation && (
            <p className="flex flex-wrap items-center gap-x-2 text-slate-700">
              <Icon name="send" className="h-4 w-4 text-slate-500" />{t(CONF[data.confirmation.status] ?? data.confirmation.status)}
              {data.confirmation.promised_delivery_date && <span>{t('· janji kirim')} <b>{formatDate(data.confirmation.promised_delivery_date)}</b></span>}
              {data.confirmation.delta_days != null && (
                <span className={`text-xs font-medium ${data.confirmation.delta_days > 0 ? 'text-red-700' : 'text-slate-500'}`}>
                  ({data.confirmation.delta_days === 0 ? t('tepat tenggat') : data.confirmation.delta_days > 0
                    ? t('{n} hari setelah tenggat {d}', { n: data.confirmation.delta_days, d: formatDate(data.confirmation.deadline) })
                    : t('{n} hari sebelum tenggat {d}', { n: -data.confirmation.delta_days, d: formatDate(data.confirmation.deadline) })})
                </span>
              )}
              {data.confirmation.supplier_reference && <span className="font-mono text-xs text-slate-500">· ref {data.confirmation.supplier_reference}</span>}
            </p>
          )}
          {data.conversations.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-500">{t('Percakapan Telegram')}</h3>
              <ul className="space-y-1">
                {data.conversations.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-center justify-between gap-2">
                    <span>{t(CONV[c.purpose] ?? c.purpose)} · <span className="text-slate-500">{t(CONV_STATUS[c.status] ?? c.status)}</span> · <span className="text-xs text-slate-500">{dayTime(c.last_activity_at)}</span></span>
                    <Link className="text-xs font-medium text-primary-700 hover:underline" to={`/supplier-hub/conversations/${c.supplier_id}`}>{t('Buka thread')}</Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.missions.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-500">{t('Misi Agent Hub')}</h3>
              <ul className="space-y-1.5">
                {data.missions.map((m) => (
                  <li key={m.id}>
                    <Link to={`/supplier-hub/missions/${m.id}`} className="flex flex-wrap items-center gap-2 font-medium text-primary-700 hover:underline">
                      {t('Misi #{n}', { n: m.number })} · {t(SCENARIO[m.scenario]?.label)} <StateBadge meta={MISSION_STATUS[m.status]} />
                    </Link>
                    {m.summary && <p className="text-xs text-slate-500">{m.summary}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.approvals.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-slate-500">{t('Ajuan terkait')}</h3>
              <ul className="space-y-1">
                {data.approvals.map((a) => (
                  <li key={a.id}><Link to={`/supplier-hub?item=${a.id}`} className="inline-flex items-center gap-2 text-primary-700 hover:underline">{t(a.title)} <StateBadge meta={DECISION[a.status] ?? DECISION.PENDING} /></Link></li>
                ))}
              </ul>
            </div>
          )}
          {!data.confirmation && !data.conversations.length && !data.missions.length && !data.approvals.length && (
            <p className="text-slate-500">{t('Belum ada komunikasi supplier untuk PO ini. Buat misi untuk menanyakan harga, stok, jadwal kirim, atau dokumen.')}</p>
          )}
        </div>
      )}
      <ConfirmDialog open={confirmCancel} title={t('Minta pembatalan PO')} confirmLabel={t('Kirim permintaan')}
        message={t('Agent meminta {supplier} menyetujui pembatalan {po} via Telegram. PO dihapus setelah supplier setuju; bila menolak, manajer diberi tahu.', { supplier: po.supplier_name, po: po.po_number })}
        loading={busy === 'CANCEL_ORDER'} onConfirm={() => start('CANCEL_ORDER')} onCancel={() => setConfirmCancel(false)} />
    </Card>
  );
}

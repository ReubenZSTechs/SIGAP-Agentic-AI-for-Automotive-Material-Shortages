import { Link } from 'react-router-dom';
import Icon from '../../../components/common/Icon';
import StateBadge from '../StateBadge';
import { DECISION, MISSION_STATUS, TELEGRAM, typeMeta } from '../meta';
import { t } from '../../../i18n';

const CONF = { PENDING: 'Menunggu konfirmasi', CONFIRMED: 'Dikonfirmasi', DECLINED: 'Ditolak supplier',
  CANCEL_PENDING: 'Menunggu pembatalan', REVISION_PENDING: 'Revisi diminta' };

function Block({ title, children }) {
  return (
    <section className="border-b border-slate-200 px-4 py-3.5 last:border-b-0">
      <h3 className="mb-2 text-xs font-semibold text-slate-500">{title}</h3>
      {children}
    </section>
  );
}
function Row({ label, children }) {
  return <div className="flex justify-between gap-3 py-0.5 text-sm"><dt className="text-slate-500">{label}</dt><dd className="text-right text-slate-800">{children}</dd></div>;
}
const linkCls = 'block rounded-lg px-2 py-1.5 -mx-2 text-sm hover:bg-slate-50';

// Konteks thread: supplier, PO terbuka, misi, ajuan, dan aturan otonomi yang berlaku.
export default function ContextPanel({ thread }) {
  const { supplier: s, context: c } = thread;
  const pending = c.approvals.filter((a) => a.status === 'PENDING');
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <Block title={t('Supplier')}>
        <p className="font-semibold text-slate-900">{s.name}</p>
        <dl className="mt-1.5">
          <Row label={t('Kode')}><span className="font-mono text-xs">{s.code}</span></Row>
          <Row label={t('Kontak')}>{s.contact_raw || '—'}</Row>
          <Row label={t('Telegram')}><StateBadge meta={TELEGRAM[s.telegram]} /></Row>
          {s.sandbox && <Row label={t('Mode')}>{t('Sandbox')}</Row>}
          <Row label={t('Respons rata-rata')}>{s.avg_response_min != null ? `${s.avg_response_min} mnt` : '—'}</Row>
        </dl>
      </Block>

      {c.pos.length > 0 && (
        <Block title={t('PO terbuka')}>
          {c.pos.map((p) => (
            <Link key={p.id} to={`/purchase-orders/${p.id}`} className={linkCls}>
              <span className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-slate-800">{p.po_number}</span><span className="text-xs text-slate-500">{p.status}</span></span>
              <span className="block text-xs text-slate-500">{t(CONF[p.confirmation] ?? p.confirmation)}</span>
            </Link>
          ))}
        </Block>
      )}

      {c.missions.length > 0 && (
        <Block title={t('Terkait')}>
          {c.missions.map((m) => (
            <Link key={m.id} to={`/supplier-hub/missions/${m.id}`} className={linkCls}>
              <span className="flex items-center justify-between gap-2"><span className="font-medium text-slate-800">{t('Misi #{n}', { n: m.number })}</span><StateBadge meta={MISSION_STATUS[m.status]} /></span>
              <span className="block text-xs text-slate-500">{t(m.title)} · {t('{replied}/{total} balas', { replied: m.replied, total: m.total })}</span>
            </Link>
          ))}
        </Block>
      )}

      <Block title={t('Ajuan Agent ({n} menunggu)', { n: pending.length })}>
        {c.approvals.length === 0 ? <p className="text-sm text-slate-500">{t('Belum ada ajuan.')}</p> : c.approvals.map((a) => (
          <Link key={a.id} to={`/supplier-hub?item=${a.id}`} className={linkCls}>
            <span className="block font-medium text-slate-800">{t(a.title)}</span>
            <span className="flex items-center gap-2 text-xs text-slate-500">{t(typeMeta(a.type).label)} · <StateBadge meta={DECISION[a.status] ?? DECISION.PENDING} /></span>
          </Link>
        ))}
      </Block>

      <Block title={t('Aturan yang berlaku')}>
        <dl>{c.rules.map((r) => <Row key={t(r.label)} label={t(r.label)}>{r.value}</Row>)}</dl>
        <Link to="/supplier-hub/settings" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline"><Icon name="sliders" className="h-3.5 w-3.5" /> {t('Ubah aturan')}</Link>
      </Block>
    </div>
  );
}

import { Link } from 'react-router-dom';
import Icon from '../../../components/common/Icon';
import StateBadge from '../StateBadge';
import { DECISION, DOC_STATUS, DOC_TYPE, MISSION_STATUS, TELEGRAM, typeMeta } from '../meta';

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

// Konteks thread: supplier, PO terbuka, misi, ajuan, dokumen, dan aturan otonomi yang berlaku.
export default function ContextPanel({ thread: t }) {
  const { supplier: s, context: c } = t;
  const pending = c.approvals.filter((a) => a.status === 'PENDING');
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <Block title="Supplier">
        <p className="font-semibold text-slate-900">{s.name}</p>
        <dl className="mt-1.5">
          <Row label="Kode"><span className="font-mono text-xs">{s.code}</span></Row>
          <Row label="Kontak">{s.contact_raw || '—'}</Row>
          <Row label="Telegram"><StateBadge meta={TELEGRAM[s.telegram]} /></Row>
          {s.sandbox && <Row label="Mode">Sandbox</Row>}
          <Row label="Respons rata-rata">{s.avg_response_min != null ? `${s.avg_response_min} mnt` : '—'}</Row>
        </dl>
      </Block>

      {c.pos.length > 0 && (
        <Block title="PO terbuka">
          {c.pos.map((p) => (
            <Link key={p.id} to={`/purchase-orders/${p.id}`} className={linkCls}>
              <span className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-slate-800">{p.po_number}</span><span className="text-xs text-slate-500">{p.status}</span></span>
              <span className="block text-xs text-slate-500">{CONF[p.confirmation] ?? p.confirmation}</span>
            </Link>
          ))}
        </Block>
      )}

      {(c.missions.length > 0 || c.documents.length > 0) && (
        <Block title="Terkait">
          {c.missions.map((m) => (
            <Link key={m.id} to={`/supplier-hub/missions/${m.id}`} className={linkCls}>
              <span className="flex items-center justify-between gap-2"><span className="font-medium text-slate-800">Misi #{m.number}</span><StateBadge meta={MISSION_STATUS[m.status]} /></span>
              <span className="block text-xs text-slate-500">{m.title} · {m.replied}/{m.total} balas</span>
            </Link>
          ))}
          {c.documents.map((d) => (
            <Link key={d.id} to={`/supplier-hub/documents/${d.id}`} className={linkCls}>
              <span className="flex items-center justify-between gap-2"><span className="font-medium text-slate-800">{DOC_TYPE[d.type] ?? 'Dokumen'}</span><StateBadge meta={DOC_STATUS[d.status]} /></span>
              <span className="block truncate font-mono text-xs text-slate-500">{d.number}</span>
            </Link>
          ))}
        </Block>
      )}

      <Block title={`Ajuan Agent (${pending.length} menunggu)`}>
        {c.approvals.length === 0 ? <p className="text-sm text-slate-500">Belum ada ajuan.</p> : c.approvals.map((a) => (
          <Link key={a.id} to={`/supplier-hub?item=${a.id}`} className={linkCls}>
            <span className="block font-medium text-slate-800">{a.title}</span>
            <span className="flex items-center gap-2 text-xs text-slate-500">{typeMeta(a.type).label} · <StateBadge meta={DECISION[a.status] ?? DECISION.PENDING} /></span>
          </Link>
        ))}
      </Block>

      <Block title="Aturan yang berlaku">
        <dl>{c.rules.map((r) => <Row key={r.label} label={r.label}>{r.value}</Row>)}</dl>
        <Link to="/supplier-hub/settings" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline"><Icon name="sliders" className="h-3.5 w-3.5" /> Ubah aturan</Link>
      </Block>
    </div>
  );
}

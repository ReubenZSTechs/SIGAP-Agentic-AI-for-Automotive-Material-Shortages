import { useState } from 'react';
import Button from '../../../components/common/Button';
import Icon from '../../../components/common/Icon';
import { Textarea } from '../../../components/common/Input';
import { CONFIDENCE, MSG_STATUS, clock } from '../meta';
import { t } from '../../../i18n';

export function AgentTile({ className = 'h-5 w-5' }) {
  return <span className={`flex items-center justify-center rounded-md bg-primary-900 text-white ${className}`} aria-hidden="true"><Icon name="spark" className="h-3 w-3" /></span>;
}

// Data hasil ekstraksi Agent. Klik membuka kartu persetujuan atau misi terkait.
function ExtractChip({ e, onOpenApproval, onOpenMission }) {
  const c = CONFIDENCE[e.confidence] ?? CONFIDENCE.MEDIUM;
  const body = (
    <>
      <i className={`h-2 w-2 rounded-full ${c.dot}`} aria-hidden="true" />
      <span className="text-slate-500">{t(e.label)}</span> <b className="tabular-nums text-slate-900">{e.value}</b>
      {e.confidence === 'LOW' && <span className="font-semibold text-red-700">{t('cek manual')}</span>}
    </>
  );
  const cls = 'inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs ring-1 ring-inset ring-slate-200';
  if (e.approval_id) return <button type="button" title={`${t(c.label)}. ${t('Buka kartu persetujuan')}`} onClick={() => onOpenApproval(e.approval_id)} className={`${cls} hover:ring-primary-400`}>{body}</button>;
  if (e.mission_id) return <button type="button" title={`${t(c.label)}. ${t('Buka misi')}`} onClick={() => onOpenMission(e.mission_id)} className={`${cls} hover:ring-primary-400`}>{body}</button>;
  return <span title={t(c.label)} className={cls}>{body}</span>;
}

function Attachment({ a, onOpen }) {
  return (
    <button type="button" onClick={() => onOpen(a)} className="mt-2 flex w-full max-w-xs items-center gap-3 rounded-lg bg-white/80 px-3 py-2 text-left ring-1 ring-inset ring-slate-200 hover:ring-primary-400">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500"><Icon name={a.kind === 'image' ? 'image' : 'file'} className="h-5 w-5" /></span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-slate-800">{a.name}</span>
        <span className="block text-xs text-slate-500">{a.outbound ? t('PO final (PDF) dikirim ke supplier') : `${a.kind === 'image' ? t('Gambar') : t('Dokumen')} · ${a.size}`}</span>
      </span>
    </button>
  );
}

function Status({ m }) {
  const s = MSG_STATUS[m.status];
  if (!s) return null;
  return (
    <span className={`inline-flex items-center gap-0.5 ${m.status === 'FAILED' ? 'text-red-700' : ''}`}>
      <Icon name={s.icon} className="h-3.5 w-3.5" />{t(s.label)}
    </span>
  );
}

// Supplier di kiri (netral); Agent di kanan (biru lembut, draf bergaris putus); admin di kanan (kontur); sistem sebagai chip di tengah.
export default function MessageBubble({ m, supplier, busy, onOpenApproval, onOpenMission, onOpenManager, onOpenAttachment, onSendDraft, onDiscard, onRetry }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.text);

  if (m.from === 'SYSTEM') {
    return (
      <div className="my-3 flex justify-center">
        <span className="inline-flex max-w-full flex-wrap items-center justify-center gap-x-2 rounded-full bg-white px-3 py-1 text-center text-xs text-slate-600 ring-1 ring-slate-200">
          {m.text}
          {m.approval_id && <button type="button" onClick={() => onOpenApproval(m.approval_id)} className="font-semibold text-primary-700 hover:underline">{t('Lihat persetujuan')}</button>}
          {m.kind === 'manager' && onOpenManager && <button type="button" onClick={onOpenManager} className="font-semibold text-primary-700 hover:underline">{t('Buka chat manajer')}</button>}
          <span className="tabular-nums text-slate-400">{clock(m.at)}</span>
        </span>
      </div>
    );
  }

  const mine = m.from !== 'SUPPLIER';
  const draft = m.status === 'DRAFT';
  const bubble = {
    SUPPLIER: 'rounded-tl-md bg-white ring-1 ring-inset ring-slate-200',
    AGENT: draft ? 'rounded-tr-md border border-dashed border-primary-400 bg-primary-50/50' : 'rounded-tr-md bg-primary-50 ring-1 ring-inset ring-primary-100',
    ADMIN: 'rounded-tr-md bg-white ring-1 ring-inset ring-primary-400',
  }[m.from];

  return (
    <div className={`my-2 flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className="w-fit max-w-[min(34rem,88%)]">
        <div className={`mb-1 flex items-center gap-1.5 text-xs text-slate-500 ${mine ? 'justify-end' : ''}`}>
          {m.from === 'AGENT' && <><AgentTile /> <b className="font-semibold text-slate-700">{t('Agent')}</b>{m.template && <span>{t('· template')}</span>}</>}
          {m.from === 'ADMIN' && <><Icon name="user" className="h-3.5 w-3.5" /> <b className="font-semibold text-slate-700">{t('Anda')}</b>{m.author && <span>· {m.author}</span>}</>}
          {m.from === 'SUPPLIER' && <b className="font-semibold text-slate-700">{supplier.contact_raw ? supplier.contact : supplier.name}</b>}
        </div>

        <div className={`rounded-2xl px-3.5 py-2.5 text-sm text-slate-800 ${bubble}`}>
          {editing ? (
            <Textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} aria-label={t('Edit draf')} className="bg-white" />
          ) : <p className="whitespace-pre-line">{m.text}</p>}
          {m.attachments.map((a) => <Attachment key={a.id} a={a} onOpen={onOpenAttachment} />)}
          {m.extracted.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {m.extracted.map((e, i) => <ExtractChip key={`${t(e.label)}-${i}`} e={e} onOpenApproval={onOpenApproval} onOpenMission={onOpenMission} />)}
            </div>
          )}
        </div>

        <div className={`mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-500 ${mine ? 'justify-end' : ''}`}>
          {draft ? <span className="font-semibold text-primary-700">Draf, belum dikirim{m.review_reason ? ` · ${m.review_reason}` : ''}</span> : <Status m={m} />}
          <span className="tabular-nums">{clock(m.at)}</span>
        </div>
        {m.status === 'FAILED' && (
          <div className="mt-1 flex flex-wrap items-center justify-end gap-2 text-xs text-red-700">
            <span>{m.error}</span>
            <Button size="sm" variant="secondary" loading={busy === `retry-${m.id}`} onClick={() => onRetry(m)}><Icon name="refresh" /> {t('Kirim ulang')}</Button>
          </div>
        )}
        {draft && (
          <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
            {editing ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setText(m.text); }}>{t('Batal')}</Button>
                <Button size="sm" disabled={text.trim().length < 2} loading={busy === `send-${m.id}`} onClick={() => onSendDraft(m, text.trim())}><Icon name="send" /> {t('Kirim')}</Button>
              </>
            ) : (
              <>
                <Button size="sm" variant="ghost" className="text-red-600" loading={busy === `discard-${m.id}`} onClick={() => onDiscard(m)}>{t('Buang')}</Button>
                <Button size="sm" variant="secondary" onClick={() => setEditing(true)}><Icon name="edit" /> {t('Edit')}</Button>
                <Button size="sm" loading={busy === `send-${m.id}`} onClick={() => onSendDraft(m, m.text)}><Icon name="send" /> {t('Kirim')}</Button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

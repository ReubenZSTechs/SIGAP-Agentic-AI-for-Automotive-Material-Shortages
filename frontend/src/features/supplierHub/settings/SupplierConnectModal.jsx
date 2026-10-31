import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import Button from '../../../components/common/Button';
import Icon from '../../../components/common/Icon';
import Input from '../../../components/common/Input';
import Modal from '../../../components/common/Modal';
import { Spinner } from '../../../components/common/EmptyState';
import StateBadge from '../StateBadge';
import { TELEGRAM, approverName } from '../meta';
import usePolling from '../../../hooks/usePolling';
import { hubService } from '../../../services/hubService';
import { toast } from '../../../store/toastStore';
import { t } from '../../../i18n';

// Undangan Telegram: deep link t.me/<bot>?start=<token> (token dari backend), salin, QR, dan status yang dipantau.
// Mode sandbox: tidak ada bot sungguhan, jadi supplier ditautkan ke chat simulasi dengan satu klik.
export default function SupplierConnectModal({ supplier, onClose, onConnected }) {
  const [invite, setInvite] = useState(null);
  const [qr, setQr] = useState(null);
  const [state, setState] = useState('PENDING');
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supplier) return;
    setInvite(null); setErr(null); setQr(null); setState(supplier.telegram === 'CONNECTED' ? 'CONNECTED' : 'PENDING');
    hubService.inviteSupplier(supplier.id, approverName()).then((r) => {
      setInvite(r);
      if (r.link) QRCode.toDataURL(r.link, { margin: 1, width: 200 }).then(setQr).catch(() => setQr(null));
    }).catch((e) => setErr(e.message));
  }, [supplier]);
  usePolling(async () => {
    try {
      const s = await hubService.getSupplier(supplier.id);
      if (s.telegram === 'CONNECTED') { setState('CONNECTED'); toast.success(t('{name} terhubung ke Telegram', { name: supplier.name })); onConnected(); }
    } catch { /* coba lagi pada putaran berikutnya */ }
  }, 3000, !!supplier && !!invite && !invite.sandbox && state !== 'CONNECTED');

  if (!supplier) return null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(invite.link); toast.success('Tautan disalin'); } catch { toast.error('Gagal menyalin. Salin manual dari kolom tautan.'); }
  };
  const linkSandbox = async () => {
    setBusy(true);
    try { await hubService.linkSandbox(supplier.id, approverName()); setState('CONNECTED'); toast.success(t('{name} ditautkan ke chat sandbox', { name: supplier.name })); onConnected(); } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal open onClose={onClose} title={t('Hubungkan {name}', { name: supplier.name })} footer={<Button variant="secondary" onClick={onClose}>{state === 'CONNECTED' ? t('Selesai') : t('Tutup')}</Button>}>
      {!invite && !err ? <Spinner label={t('Menyiapkan undangan…')} /> : (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-slate-600">{t('Status')}</span>
            <span className="inline-flex items-center gap-2">
              {state === 'PENDING' && invite && !invite.sandbox && <svg className="h-3.5 w-3.5 animate-spin text-amber-600" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" /><path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" /></svg>}
              <StateBadge meta={TELEGRAM[state]} />
            </span>
          </div>
          {err && <p role="alert" className="text-sm text-red-600">{t(err)}</p>}
          {invite && state !== 'CONNECTED' && invite.sandbox && (
            <div className="rounded-lg bg-slate-50 px-3.5 py-3 text-sm text-slate-700">
              <p>{t('Mode')} <b>{t('sandbox')}</b>{t(': pesan hanya disimpan di database. Tautkan supplier ke chat simulasi, lalu balasannya bisa diketik di thread percakapan.')}</p>
              <Button className="mt-3" loading={busy} onClick={linkSandbox}><Icon name="link" /> {t('Tautkan ke chat sandbox')}</Button>
            </div>
          )}
          {invite && state !== 'CONNECTED' && !invite.sandbox && (invite.link ? (
            <>
              <p className="text-sm text-slate-700">{t('Kirim tautan ini ke {contact}. Setelah ia menekan', { contact: supplier.contact })} <b>{t('Start')}</b> {t('di Telegram, status berubah menjadi Terhubung.')}</p>
              <div className="flex gap-2">
                <Input readOnly value={invite.link} className="font-mono text-xs" aria-label={t('Tautan undangan')} onFocus={(e) => e.target.select()} />
                <Button variant="secondary" onClick={copy}><Icon name="copy" /> {t('Salin')}</Button>
              </div>
              {qr && (
                <div className="flex flex-col items-center gap-1.5">
                  <img src={qr} alt={t('Kode QR undangan Telegram untuk {name}', { name: supplier.name })} className="h-44 w-44 rounded-lg ring-1 ring-slate-200" />
                  <span className="text-xs text-slate-500">{t('Atau pindai dengan kamera ponsel.')}</span>
                </div>
              )}
            </>
          ) : (
            <p className="rounded-lg bg-amber-50 px-3.5 py-3 text-sm text-amber-900">{t('TELEGRAM_BOT_USERNAME belum diisi di backend/.env, jadi tautan undangan belum bisa dibuat.')}</p>
          ))}
          {state === 'CONNECTED' && (
            <p className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2.5 text-sm text-green-800"><Icon name="check" className="h-4 w-4" /> {t('Terhubung. Agent kini bisa mengirim pesan ke {name}.', { name: supplier.name })}</p>
          )}
        </div>
      )}
    </Modal>
  );
}

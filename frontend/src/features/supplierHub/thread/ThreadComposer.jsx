import { useState } from 'react';
import Button from '../../../components/common/Button';
import Icon from '../../../components/common/Icon';
import { Select, Textarea } from '../../../components/common/Input';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { COMPANY, fillTemplate, greeting } from '../../../utils/template';
import { t } from '../../../i18n';

// Saat Agent menangani thread, composer diganti ajakan Ambil alih (pesan manual hanya setelah Agent dijeda di thread ini).
export default function ThreadComposer({ thread, busy, onSend, onTakeover }) {
  const [text, setText] = useState('');
  const tpl = useFetch(() => hubService.getTemplates(), []);

  if (thread.mode !== 'HUMAN') {
    return (
      <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <Icon name="spark" className="h-4 w-4 text-primary-600" />
        <span className="flex-1">{t('Agent sedang menangani percakapan ini. Ambil alih untuk mengirim pesan manual.')}</span>
        <Button size="sm" variant="secondary" loading={busy === 'takeover'} onClick={onTakeover}><Icon name="user" /> {t('Ambil alih')}</Button>
      </div>
    );
  }
  const connected = thread.supplier.telegram === 'CONNECTED';

  const applyTemplate = (id) => {
    const item = tpl.data?.find((x) => String(x.id) === id);
    if (item) setText(fillTemplate(item.body, { waktu: greeting(), kontak: thread.supplier.contact, supplier: thread.supplier.name, perusahaan: COMPANY }));
  };
  const send = async () => {
    if (!text.trim()) return;
    if (await onSend(text.trim())) setText('');
  };

  return (
    <div className="border-t border-slate-200 bg-white px-4 py-3">
      <Textarea rows={2} value={text} placeholder={connected ? t('Ketik pesan untuk supplier…') : t('Supplier belum terhubung ke Telegram')} aria-label={t('Pesan')}
        disabled={!connected} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Select className="h-8 w-auto! min-w-0 text-xs" value="" aria-label={t('Sisipkan template')} disabled={!connected} onChange={(e) => applyTemplate(e.target.value)}>
          <option value="">{t('Template…')}</option>
          {(tpl.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </Select>
        <span className="ml-auto hidden text-xs text-slate-400 sm:inline">{t('Ctrl+Enter untuk kirim')}</span>
        <Button size="sm" loading={busy === 'send'} disabled={!text.trim() || !connected} onClick={send}><Icon name="send" /> {t('Kirim')}</Button>
      </div>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-800"><Icon name="pause" className="h-3.5 w-3.5" /> {t('Agent dijeda untuk supplier ini. Pesan Anda langsung dikirim ke supplier.')}</p>
    </div>
  );
}

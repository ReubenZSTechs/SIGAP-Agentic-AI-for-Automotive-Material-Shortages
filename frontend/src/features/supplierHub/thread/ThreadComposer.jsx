import { useState } from 'react';
import Button from '../../../components/common/Button';
import Icon from '../../../components/common/Icon';
import { Select, Textarea } from '../../../components/common/Input';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { COMPANY, fillTemplate, greeting } from '../../../utils/template';

// Saat Agent menangani thread, composer diganti ajakan Ambil alih (pesan manual hanya setelah Agent dijeda di thread ini).
export default function ThreadComposer({ thread, busy, onSend, onTakeover }) {
  const [text, setText] = useState('');
  const tpl = useFetch(() => hubService.getTemplates(), []);

  if (thread.mode !== 'HUMAN') {
    return (
      <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <Icon name="spark" className="h-4 w-4 text-primary-600" />
        <span className="flex-1">Agent sedang menangani percakapan ini. Ambil alih untuk mengirim pesan manual.</span>
        <Button size="sm" variant="secondary" loading={busy === 'takeover'} onClick={onTakeover}><Icon name="user" /> Ambil alih</Button>
      </div>
    );
  }
  const connected = thread.supplier.telegram === 'CONNECTED';

  const applyTemplate = (id) => {
    const t = tpl.data?.find((x) => String(x.id) === id);
    if (t) setText(fillTemplate(t.body, { waktu: greeting(), kontak: thread.supplier.contact, supplier: thread.supplier.name, perusahaan: COMPANY }));
  };
  const send = async () => {
    if (!text.trim()) return;
    if (await onSend(text.trim())) setText('');
  };

  return (
    <div className="border-t border-slate-200 bg-white px-4 py-3">
      <Textarea rows={2} value={text} placeholder={connected ? 'Ketik pesan untuk supplier…' : 'Supplier belum terhubung ke Telegram'} aria-label="Pesan"
        disabled={!connected} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Select className="h-8 w-auto! min-w-0 text-xs" value="" aria-label="Sisipkan template" disabled={!connected} onChange={(e) => applyTemplate(e.target.value)}>
          <option value="">Template…</option>
          {(tpl.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
        <span className="ml-auto hidden text-xs text-slate-400 sm:inline">Ctrl+Enter untuk kirim</span>
        <Button size="sm" loading={busy === 'send'} disabled={!text.trim() || !connected} onClick={send}><Icon name="send" /> Kirim</Button>
      </div>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-800"><Icon name="pause" className="h-3.5 w-3.5" /> Agent dijeda untuk supplier ini. Pesan Anda langsung dikirim ke supplier.</p>
    </div>
  );
}

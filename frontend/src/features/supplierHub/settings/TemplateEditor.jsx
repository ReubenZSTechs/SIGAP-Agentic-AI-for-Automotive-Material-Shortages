import { useEffect, useRef, useState } from 'react';
import Button from '../../../components/common/Button';
import Card from '../../../components/common/Card';
import FormField from '../../../components/common/FormField';
import Icon from '../../../components/common/Icon';
import Input, { Select, Textarea } from '../../../components/common/Input';
import { Spinner } from '../../../components/common/EmptyState';
import { AgentTile } from '../thread/MessageBubble';
import { SCENARIO } from '../meta';
import useFetch from '../../../hooks/useFetch';
import { hubService } from '../../../services/hubService';
import { toast } from '../../../store/toastStore';
import { SAMPLE_VARS, TEMPLATE_VARS, templateParts } from '../../../utils/template';
import { t } from '../../../i18n';

const SCENARIO_OPTS = { ...Object.fromEntries(Object.entries(SCENARIO).map(([k, v]) => [k, v.label])), REMINDER: 'Pengingat', OTHER: 'Lainnya' };
const blank = () => ({ id: null, name: 'Template baru', scenario: 'OTHER', body: 'Selamat {waktu} {kontak}, ' });

// Daftar template di kiri, editor + pratinjau dengan contoh nilai variabel di kanan.
export default function TemplateEditor() {
  const { data, loading, error, reload } = useFetch(() => hubService.getTemplates(), []);
  const [sel, setSel] = useState(null);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef(null);

  useEffect(() => { // pilih template pertama saat data tiba
    if (data && !draft) { setSel(data[0]?.id ?? null); setDraft(data[0] ? { ...data[0] } : blank()); }
  }, [data, draft]);

  if (error) return <Card><p className="text-sm text-red-600">{error.message}</p><Button className="mt-3" variant="secondary" onClick={reload}>{t('Coba lagi')}</Button></Card>;
  if (loading && !data) return <Spinner />;
  if (!draft) return null;

  const original = data.find((item) => item.id === draft.id);
  const dirty = !original || JSON.stringify(original) !== JSON.stringify(draft);
  const pick = (item) => {
    if (dirty && !window.confirm('Buang perubahan template yang belum disimpan?')) return;
    setSel(item?.id ?? null); setDraft(item ? { ...t } : blank());
  };
  const insertVar = (key) => { // sisipkan di posisi kursor
    const el = bodyRef.current;
    const at = el?.selectionStart ?? draft.body.length;
    const body = `${draft.body.slice(0, at)}{${key}}${draft.body.slice(el?.selectionEnd ?? at)}`;
    setDraft((d) => ({ ...d, body }));
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(at + key.length + 2, at + key.length + 2); });
  };
  const save = async () => {
    if (draft.name.trim().length < 3 || draft.body.trim().length < 10) return toast.error('Nama minimal 3 karakter dan isi pesan minimal 10 karakter');
    setBusy(true);
    try {
      const saved = await hubService.saveTemplate({ ...draft, name: draft.name.trim() });
      toast.success('Template disimpan');
      await reload(); setSel(saved.id); setDraft(saved);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
    return undefined;
  };
  const unknown = templateParts(draft.body, SAMPLE_VARS).filter((p) => p.key?.startsWith('!'));

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <Card padded={false}>
        <ul className="divide-y divide-slate-100">
          {data.map((item) => (
            <li key={item.id}>
              <button type="button" onClick={() => pick(item)} aria-current={sel === item.id ? 'true' : undefined}
                className={`block w-full border-l-[3px] px-4 py-3 text-left transition-colors ${sel === item.id ? 'border-l-primary-600 bg-primary-50' : 'border-l-transparent hover:bg-slate-50'}`}>
                <span className="block text-sm font-semibold text-slate-900">{item.name}</span>
                <span className="text-xs text-slate-500">{SCENARIO_OPTS[item.scenario] ?? item.scenario}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="border-t border-slate-200 p-3"><Button variant="secondary" size="sm" className="w-full" onClick={() => pick(null)}><Icon name="plus" /> {t('Template baru')}</Button></div>
      </Card>

      <Card title={draft.id ? t('Edit template') : t('Template baru')} actions={dirty && <span className="text-xs font-medium text-amber-700">{t('Belum disimpan')}</span>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label={t('Nama')}><Input value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} /></FormField>
          <FormField label={t('Skenario')}>
            <Select value={draft.scenario} onChange={(e) => setDraft((d) => ({ ...d, scenario: e.target.value }))}>
              {Object.entries(SCENARIO_OPTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </FormField>
        </div>
        <FormField className="mt-3" label={t('Isi pesan')}>
          <Textarea ref={bodyRef} rows={5} value={draft.body} onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))} />
        </FormField>
        <div className="mt-2">
          <p className="mb-1.5 text-xs text-slate-500">{t('Sisipkan variabel:')}</p>
          <div className="flex flex-wrap gap-1.5">
            {TEMPLATE_VARS.map((v) => (
              <button key={v.key} type="button" title={t(v.label)} onClick={() => insertVar(v.key)}
                className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700 hover:bg-primary-50 hover:text-primary-700">{`{${v.key}}`}</button>
            ))}
          </div>
          {unknown.length > 0 && <p role="alert" className="mt-2 text-xs font-medium text-red-600">Variabel tidak dikenal: {unknown.map((p) => p.text).join(', ')}</p>}
        </div>

        <div className="mt-5">
          <p className="mb-1.5 text-sm font-medium text-slate-700">{t('Pratinjau dengan contoh nilai')}</p>
          <div className="rounded-xl bg-slate-50 p-4">
            <div className="ml-auto w-fit max-w-[90%]">
              <div className="mb-1 flex items-center justify-end gap-1.5 text-xs text-slate-500"><AgentTile /> <b className="font-semibold text-slate-700">{t('Agent')}</b> {t('· template')}</div>
              <p className="whitespace-pre-line rounded-2xl rounded-tr-md bg-primary-50 px-3.5 py-2.5 text-sm text-slate-800 ring-1 ring-inset ring-primary-100">
                {templateParts(draft.body, SAMPLE_VARS).map((p, i) => (p.key
                  ? <mark key={i} className={`rounded px-0.5 ${p.key.startsWith('!') ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-slate-900'}`}>{p.text}</mark>
                  : <span key={i}>{p.text}</span>))}
              </p>
            </div>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2 border-t border-slate-200 pt-4">
          {dirty && original && <Button variant="secondary" onClick={() => setDraft({ ...original })}>{t('Batalkan')}</Button>}
          <Button loading={busy} disabled={!dirty} onClick={save}>{t('Simpan template')}</Button>
        </div>
      </Card>
    </div>
  );
}

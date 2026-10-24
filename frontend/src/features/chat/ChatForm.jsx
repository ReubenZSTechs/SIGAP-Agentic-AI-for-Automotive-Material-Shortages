// Formulir yang dikirim Agent di chat (blok `form`): produk final, material beli, atau supplier baru.
// Alur: isi -> "Tinjau & lanjutkan" (cek kolom wajib di browser) -> server memeriksa semua aturan ->
// kartu konfirmasi -> data disimpan. Formulir hanya bisa diubah selama masih menjadi pesan terakhir.
import { useEffect, useState } from 'react';
import Button from '../../components/common/Button';
import MaterialForm from './forms/MaterialForm';
import ProductForm from './forms/ProductForm';
import SupplierForm from './forms/SupplierForm';
import { checkRequired, setIn } from './formUtils';
import { t } from '../../i18n';

const BODY = { product: ProductForm, material: MaterialForm, supplier: SupplierForm };

export default function ChatForm({ block, editable, onSubmit, onCancel }) {
  const [values, setValues] = useState(block.values);
  const [errors, setErrors] = useState(block.errors ?? {});

  useEffect(() => {
    setValues(block.values);
    setErrors(block.errors ?? {});
  }, [block]);

  const form = {
    formId: block.formId,
    values,
    errors,
    disabled: !editable,
    set: (path, value) => {
      setValues((v) => setIn(v, path, value));
      setErrors((e) => {                       // kolom yang diubah tidak lagi ditandai salah
        const next = { ...e };
        Object.keys(next).filter((k) => k === path || k.startsWith(`${path}.`)).forEach((k) => delete next[k]);
        return next;
      });
    },
  };

  const submit = () => {
    const missing = checkRequired(block.entity, values);
    setErrors(missing);
    if (Object.keys(missing).length === 0) onSubmit(block.formId, values, block.title);
  };

  // Kembali ke template kosong (mis. setelah salah isi dan ingin mulai dari awal).
  const reset = () => {
    setValues(block.emptyValues ?? block.values);
    setErrors({});
  };

  const Body = BODY[block.entity];
  const errorCount = Object.keys(errors).length;
  return (
    <div className="my-2 rounded-xl border border-l-4 border-indigo-200 border-l-indigo-600 bg-slate-50/70 p-4">
      <div className="mb-3 text-sm font-medium text-slate-900">{t(block.title)}</div>
      {editable && errorCount > 0 && (
        <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {errorCount} isian perlu diperbaiki (ditandai merah). Perbaiki lalu kirim lagi, atau kosongkan formulir untuk mulai dari awal.
        </p>
      )}
      {errors._form && <p role="alert" className="mb-2 text-xs font-medium text-red-600">{errors._form}</p>}
      <Body form={form} options={block.options} hints={block.hints} />
      {editable ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={submit}>{block.submitLabel ?? 'Lanjutkan'}</Button>
          <Button size="sm" variant="ghost" onClick={reset}>{t('Kosongkan formulir')}</Button>
          <Button size="sm" variant="secondary" onClick={() => onCancel(block.formId)}>{t('Batal')}</Button>
          {errorCount > 0 && <span className="text-xs text-red-600">{errorCount} isian perlu diperbaiki</span>}
        </div>
      ) : (
        <p className="mt-3 text-xs text-slate-500">{t('Formulir ini sudah dikirim atau digantikan.')}</p>
      )}
    </div>
  );
}

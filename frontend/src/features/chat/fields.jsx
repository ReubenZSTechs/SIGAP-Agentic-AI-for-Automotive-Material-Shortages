// Komponen isian kecil yang dipakai bersama oleh ketiga formulir chat.
import Icon from '../../components/common/Icon';
import { getIn } from './formUtils';
import { t } from '../../i18n';

const inputCls = `w-full h-8 rounded-md border bg-white px-2.5 text-sm text-slate-900 placeholder:text-slate-400
  focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20
  disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500`;

/**
 * Satu kolom isian. `form` = { values, errors, set, disabled } dari ChatForm.
 * kind: text | number | textarea | select | checkbox
 */
export function Field({ form, path, label, kind = 'text', required = false, placeholder, options, className = '', step }) {
  const value = getIn(form.values, path);
  const error = form.errors[path];
  const id = `f-${form.formId}-${path}`;
  const border = error ? 'border-red-400' : 'border-slate-300';

  if (kind === 'checkbox') {
    return (
      <label htmlFor={id} className={`flex items-center gap-2 pt-5 text-xs text-slate-700 ${className}`}>
        <input id={id} type="checkbox" checked={!!value} disabled={form.disabled}
          onChange={(e) => form.set(path, e.target.checked)} />
        {label}
      </label>
    );
  }

  let input;
  if (kind === 'select') {
    input = (
      <select id={id} className={`${inputCls} ${border}`} value={value ?? ''} disabled={form.disabled}
        onChange={(e) => form.set(path, e.target.value === '' ? null : Number(e.target.value))}>
        <option value="">{placeholder ?? t('— pilih —')}</option>
        {options.map((o) => <option key={o.value} value={o.value}>{t(o.label)}</option>)}
      </select>
    );
  } else if (kind === 'textarea') {
    input = (
      <textarea id={id} rows={2} className={`${inputCls} ${border} h-auto py-1.5`} value={value ?? ''}
        placeholder={placeholder} disabled={form.disabled} onChange={(e) => form.set(path, e.target.value)} />
    );
  } else {
    input = (
      <input id={id} type={kind === 'number' ? 'number' : 'text'} min={kind === 'number' ? 0 : undefined}
        step={step ?? (kind === 'number' ? 'any' : undefined)} className={`${inputCls} ${border}`}
        value={value ?? ''} placeholder={placeholder} disabled={form.disabled}
        onChange={(e) => form.set(path, e.target.value)} />
    );
  }

  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-600">
        {label}{required && <span className="text-red-600"> *</span>}
      </label>
      {input}
      {error && <p role="alert" className="mt-1 text-xs font-medium text-red-600">{t(error)}</p>}
    </div>
  );
}

/**
 * Dropdown "pilih yang sudah ada" + pilihan "+ ... baru". Memilih "baru" mengisi `newKey` dengan objek kosong
 * sehingga kolom isian item baru muncul di bawahnya.
 */
export function ItemPicker({ form, base, idKey, newKey, options, newLabel, emptyNew, label }) {
  const row = getIn(form.values, base);
  const isNew = !!row[newKey];
  const path = `${base}.${idKey}`;
  const error = form.errors[path];
  const onChange = (e) => {
    const v = e.target.value;
    if (v === '__new__') form.set(base, { ...row, [idKey]: null, [newKey]: { ...emptyNew } });
    else form.set(base, { ...row, [idKey]: v === '' ? null : Number(v), [newKey]: null });
  };
  return (
    <div className="min-w-0 flex-1">
      <label htmlFor={`f-${form.formId}-${path}`} className="mb-1 block text-xs font-medium text-slate-600">
        {label}<span className="text-red-600"> *</span>
      </label>
      <select id={`f-${form.formId}-${path}`} disabled={form.disabled}
        className={`${inputCls} ${error ? 'border-red-400' : 'border-slate-300'}`}
        value={isNew ? '__new__' : (row[idKey] ?? '')} onChange={onChange}>
        <option value="">{t('— pilih —')}</option>
        <option value="__new__">{newLabel}</option>
        {options.map((o) => <option key={o.value} value={o.value}>{t(o.label)}</option>)}
      </select>
      {error && <p role="alert" className="mt-1 text-xs font-medium text-red-600">{t(error)}</p>}
    </div>
  );
}

/** Kolom untuk material beli baru (dipakai di formulir produk dan supplier). */
export function NewMaterialFields({ form, base, hint }) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 rounded-md border border-dashed border-indigo-200 bg-indigo-50/40 p-2.5 sm:grid-cols-4">
      <p className="col-span-full text-xs font-medium text-indigo-700">{t('Material beli baru')}</p>
      <Field form={form} path={`${base}.sku`} label={t('SKU')} required placeholder={t('mis. {x}', { x: hint })} />
      <Field form={form} path={`${base}.name`} label={t('Nama')} required className="col-span-1 sm:col-span-2" />
      <Field form={form} path={`${base}.uom`} label={t('Satuan')} required placeholder={t('Buah, kg, m²')} />
      <Field form={form} path={`${base}.initial_stock`} label={t('Stok awal')} kind="number" />
      <Field form={form} path={`${base}.safety_stock`} label={t('Safety stock (opsional)')} kind="number" placeholder="0" />
    </div>
  );
}

/** Kolom untuk supplier baru (dipakai di formulir material). */
export function NewSupplierFields({ form, base, hint }) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 rounded-md border border-dashed border-indigo-200 bg-indigo-50/40 p-2.5 sm:grid-cols-4">
      <p className="col-span-full text-xs font-medium text-indigo-700">{t('Supplier baru')}</p>
      <Field form={form} path={`${base}.code`} label={t('Kode')} required placeholder={t('mis. {x}', { x: hint })} />
      <Field form={form} path={`${base}.name`} label={t('Nama')} required />
      <Field form={form} path={`${base}.contact`} label={t('Kontak')} placeholder={t('Telepon / email')} />
      <Field form={form} path={`${base}.payment_term_days`} label={t('Termin (hari)')} kind="number" step="1" />
    </div>
  );
}

/** Harga, lead time, MOQ, preferred untuk relasi material–supplier. */
export function LinkTerms({ form, base }) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Field form={form} path={`${base}.unit_price`} label={t('Harga/unit (Rp)')} kind="number" step="1" required />
      <Field form={form} path={`${base}.lead_time_days`} label={t('Lead time (hari)')} kind="number" step="1" required />
      <Field form={form} path={`${base}.moq`} label={t('MOQ')} kind="number" />
      <Field form={form} path={`${base}.is_preferred`} label={t('Supplier utama')} kind="checkbox" />
    </div>
  );
}

/** Daftar baris dengan tombol tambah & hapus. `renderRow(base, index)` menggambar isi satu baris. */
export function RowList({ form, listKey, title, emptyText, addLabel, newRow, renderRow }) {
  const rows = form.values[listKey] ?? [];
  return (
    <fieldset className="mt-4">
      <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</legend>
      {rows.length === 0 && <p className="mb-2 text-xs text-slate-500">{emptyText}</p>}
      <div className="space-y-2">
        {rows.map((_, i) => (
          <div key={i} className="relative rounded-lg border border-slate-200 bg-white p-2.5 pr-9">
            {renderRow(`${listKey}.${i}`, i)}
            {!form.disabled && (
              <button type="button" aria-label={t('Hapus baris')} title={t('Hapus baris')}
                onClick={() => form.set(listKey, rows.filter((__, j) => j !== i))}
                className="absolute right-2 top-2 rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600">
                <Icon name="trash" className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>
      {!form.disabled && (
        <button type="button" onClick={() => form.set(listKey, [...rows, newRow()])}
          className="mt-2 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-50">
          <Icon name="plus" className="h-3.5 w-3.5" /> {addLabel}
        </button>
      )}
    </fieldset>
  );
}

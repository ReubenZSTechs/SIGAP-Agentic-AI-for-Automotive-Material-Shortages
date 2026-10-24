// Formulir produk final baru: data produk + komponen BOM (material yang ada atau material baru).
import { Field, ItemPicker, NewMaterialFields, NewSupplierFields, RowList } from '../fields';
import { EMPTY_NEW_MATERIAL, EMPTY_NEW_SUPPLIER, emptyRow, getIn } from '../formUtils';
import { t } from '../../../i18n';

/** Supplier for a NEW material: none, an existing supplier, or "+ Supplier baru" (opens supplier fields). */
function SupplierChoice({ form, base, options, hint }) {
  const material = getIn(form.values, base);
  const value = material.new_supplier ? '__new__' : (material.supplier_id ?? '');
  const onChange = (e) => {
    const v = e.target.value;
    if (v === '__new__') form.set(base, { ...material, supplier_id: null, new_supplier: { ...EMPTY_NEW_SUPPLIER } });
    else form.set(base, { ...material, supplier_id: v === '' ? null : Number(v), new_supplier: null });
  };
  const id = `f-${form.formId}-${base}.supplier_id`;
  const error = form.errors[`${base}.supplier_id`];
  const linked = material.new_supplier || material.supplier_id != null;
  return (
    <>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="col-span-2">
          <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-600">{t('Supplier (opsional)')}</label>
          <select id={id} value={value} onChange={onChange} disabled={form.disabled}
            className={`w-full h-8 rounded-md border bg-white px-2.5 text-sm text-slate-900 focus:border-primary-500 focus:outline-none
              focus:ring-2 focus:ring-primary-500/20 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500
              ${error ? 'border-red-400' : 'border-slate-300'}`}>
            <option value="">{t('— tanpa supplier —')}</option>
            <option value="__new__">{t('+ Supplier baru')}</option>
            {options.map((o) => <option key={o.value} value={o.value}>{t(o.label)}</option>)}
          </select>
          {error && <p role="alert" className="mt-1 text-xs font-medium text-red-600">{error}</p>}
        </div>
        {linked && (
          <>
            <Field form={form} path={`${base}.unit_price`} label={t('Harga/unit (Rp)')} kind="number" step="1" required />
            <Field form={form} path={`${base}.lead_time_days`} label={t('Lead time (hari)')} kind="number" step="1" required />
          </>
        )}
      </div>
      {material.new_supplier && <NewSupplierFields form={form} base={`${base}.new_supplier`} hint={hint} />}
    </>
  );
}

export default function ProductForm({ form, options, hints }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Field form={form} path="sku" label={t('SKU')} required placeholder={t('mis. {x}', { x: hints.product_sku })} />
        <Field form={form} path="name" label={t('Nama produk')} required className="col-span-1 sm:col-span-2" />
        <Field form={form} path="uom" label={t('Satuan')} required />
        <Field form={form} path="selling_price" label={t('Harga jual (Rp)')} kind="number" step="1" required />
        <Field form={form} path="specification" label={t('Spesifikasi')} kind="textarea" className="col-span-full sm:col-span-3" />
      </div>

      <RowList
        form={form}
        listKey="components"
        title={t('Komponen BOM (per 1 unit produk)')}
        emptyText={t('Belum ada komponen. Produk tetap bisa disimpan, tetapi belum bisa dijadwalkan produksi.')}
        addLabel={t('Tambah komponen')}
        newRow={() => emptyRow('product')}
        renderRow={(base) => {
          const row = getIn(form.values, base);
          return (
            <>
              <div className="flex items-start gap-2">
                <ItemPicker form={form} base={base} idKey="material_id" newKey="new_material" label={t('Material')}
                  options={options.materials} newLabel={t('+ Material baru')} emptyNew={EMPTY_NEW_MATERIAL} />
                <Field form={form} path={`${base}.qty`} label={t('Qty')} kind="number" required className="w-24" />
              </div>
              {row.new_material && (
                <>
                  <NewMaterialFields form={form} base={`${base}.new_material`} hint={hints.material_sku} />
                  <SupplierChoice form={form} base={`${base}.new_material`} options={options.suppliers}
                    hint={hints.supplier_code} />
                </>
              )}
            </>
          );
        }}
      />
    </>
  );
}

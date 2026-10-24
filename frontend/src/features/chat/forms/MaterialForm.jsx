// Formulir material beli baru: data material + stok awal + supplier (yang ada atau supplier baru).
import { Field, ItemPicker, LinkTerms, NewSupplierFields, RowList } from '../fields';
import { EMPTY_NEW_SUPPLIER, emptyRow, getIn } from '../formUtils';
import { t } from '../../../i18n';

export default function MaterialForm({ form, options, hints }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Field form={form} path="sku" label={t('SKU')} required placeholder={t('mis. {x}', { x: hints.material_sku })} />
        <Field form={form} path="name" label={t('Nama material')} required className="col-span-1 sm:col-span-2" />
        <Field form={form} path="uom" label={t('Satuan')} required placeholder={t('Buah, kg, m²')} />
        <Field form={form} path="initial_stock" label={t('Stok awal')} kind="number" />
        <Field form={form} path="safety_stock" label={t('Safety stock')} kind="number" />
      </div>

      <RowList
        form={form}
        listKey="suppliers"
        title={t('Supplier')}
        emptyText={t('Belum ada supplier. Material tanpa supplier belum bisa dibuatkan PO.')}
        addLabel={t('Tambah supplier')}
        newRow={() => emptyRow('material')}
        renderRow={(base) => (
          <>
            <ItemPicker form={form} base={base} idKey="supplier_id" newKey="new_supplier" label={t('Supplier')}
              options={options.suppliers} newLabel={t('+ Supplier baru')} emptyNew={EMPTY_NEW_SUPPLIER} />
            {getIn(form.values, base).new_supplier && (
              <NewSupplierFields form={form} base={`${base}.new_supplier`} hint={hints.supplier_code} />
            )}
            <LinkTerms form={form} base={base} />
          </>
        )}
      />
    </>
  );
}

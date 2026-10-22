// Formulir material beli baru: data material + stok awal + supplier (yang ada atau supplier baru).
import { Field, ItemPicker, LinkTerms, NewSupplierFields, RowList } from '../fields';
import { EMPTY_NEW_SUPPLIER, emptyRow, getIn } from '../formUtils';

export default function MaterialForm({ form, options, hints }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Field form={form} path="sku" label="SKU" required placeholder={`mis. ${hints.material_sku}`} />
        <Field form={form} path="name" label="Nama material" required className="col-span-1 sm:col-span-2" />
        <Field form={form} path="uom" label="Satuan" required placeholder="Buah, kg, m²" />
        <Field form={form} path="initial_stock" label="Stok awal" kind="number" />
        <Field form={form} path="safety_stock" label="Safety stock" kind="number" />
      </div>

      <RowList
        form={form}
        listKey="suppliers"
        title="Supplier"
        emptyText="Belum ada supplier. Material tanpa supplier belum bisa dibuatkan PO."
        addLabel="Tambah supplier"
        newRow={() => emptyRow('material')}
        renderRow={(base) => (
          <>
            <ItemPicker form={form} base={base} idKey="supplier_id" newKey="new_supplier" label="Supplier"
              options={options.suppliers} newLabel="+ Supplier baru" emptyNew={EMPTY_NEW_SUPPLIER} />
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

// Formulir supplier baru: data supplier + material yang dipasok (material yang ada atau material baru).
import { Field, ItemPicker, LinkTerms, NewMaterialFields, RowList } from '../fields';
import { EMPTY_NEW_MATERIAL, emptyRow, getIn } from '../formUtils';

export default function SupplierForm({ form, options, hints }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Field form={form} path="code" label="Kode supplier" required placeholder={`mis. ${hints.supplier_code}`} />
        <Field form={form} path="name" label="Nama supplier" required className="col-span-1 sm:col-span-2" />
        <Field form={form} path="payment_term_days" label="Termin (hari)" kind="number" step="1" />
        <Field form={form} path="contact" label="Kontak" placeholder="Telepon / email / alamat" className="col-span-full" />
      </div>

      <RowList
        form={form}
        listKey="materials"
        title="Material yang dipasok"
        emptyText="Belum ada material. Supplier tetap bisa disimpan dan dihubungkan nanti."
        addLabel="Tambah material"
        newRow={() => emptyRow('supplier')}
        renderRow={(base) => (
          <>
            <ItemPicker form={form} base={base} idKey="material_id" newKey="new_material" label="Material"
              options={options.materials} newLabel="+ Material baru" emptyNew={EMPTY_NEW_MATERIAL} />
            {getIn(form.values, base).new_material && (
              <NewMaterialFields form={form} base={`${base}.new_material`} hint={hints.material_sku} />
            )}
            <LinkTerms form={form} base={base} />
          </>
        )}
      />
    </>
  );
}

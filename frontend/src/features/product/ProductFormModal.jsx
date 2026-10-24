import { useEffect, useState } from 'react';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input, { Textarea } from '../../components/common/Input';
import { productService } from '../../services/productService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';

const EMPTY = { sku: '', name: '', uom: 'Unit', selling_price: '', specification: '', is_active: true };

// product = null -> tambah; product = {...} -> edit (SKU dikunci)
export default function ProductFormModal({ open, product, onClose, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const isEdit = !!product;

  useEffect(() => {
    if (!open) return;
    setForm(product ? { ...product, selling_price: String(product.selling_price), specification: product.specification ?? '' } : EMPTY);
    setErrors({});
  }, [open, product]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const submit = async () => {
    const er = {};
    if (!form.sku.trim() || form.sku.trim().length < 2) er.sku = 'SKU wajib diisi (min. 2 karakter)';
    if (!form.name.trim()) er.name = 'Nama wajib diisi';
    if (!form.uom.trim()) er.uom = 'Satuan wajib diisi';
    const price = Number(form.selling_price);
    if (form.selling_price === '' || !Number.isInteger(price) || price < 0) er.selling_price = 'Harga jual harus bilangan bulat ≥ 0';
    setErrors(er);
    if (Object.keys(er).length) return;

    setSaving(true);
    try {
      const spec = form.specification.trim() || null;
      if (isEdit) {
        await productService.update(product.id, {
          name: form.name.trim(), uom: form.uom.trim(), selling_price: price,
          specification: spec, is_active: form.is_active,
        });
      } else {
        await productService.create({
          sku: form.sku.trim(), name: form.name.trim(), uom: form.uom.trim(),
          selling_price: price, specification: spec,
        });
      }
      toast.success(isEdit ? 'Produk diperbarui' : 'Produk ditambahkan — lanjutkan dengan menyusun BOM');
      onSaved();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Produk Final' : 'Tambah Produk Final'}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button loading={saving} onClick={submit}>{t('Simpan')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <FormField label={t('SKU / Kode Produk')} error={errors.sku}>
          <Input value={form.sku} onChange={set('sku')} disabled={isEdit} placeholder={t('FG-XXX-01')} />
        </FormField>
        <FormField label={t('Nama Produk')} error={errors.name}>
          <Input value={form.name} onChange={set('name')} />
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t('Satuan')} error={errors.uom}>
            <Input value={form.uom} onChange={set('uom')} />
          </FormField>
          <FormField label={t('Harga Jual (Rp)')} error={errors.selling_price}>
            <Input type="number" min="0" step="1" value={form.selling_price} onChange={set('selling_price')} />
          </FormField>
        </div>
        <FormField label={t('Spesifikasi')} hint={t('Opsional — maks. 500 karakter.')}>
          <Textarea value={form.specification} onChange={set('specification')} maxLength={500} />
        </FormField>
        {isEdit && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_active} onChange={set('is_active')} /> Aktif
          </label>
        )}
      </div>
    </Modal>
  );
}

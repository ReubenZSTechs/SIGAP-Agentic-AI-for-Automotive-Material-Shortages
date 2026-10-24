import { useEffect, useState } from 'react';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input from '../../components/common/Input';
import { materialService } from '../../services/materialService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';

const EMPTY = { sku: '', name: '', uom: '', is_active: true };

// material = null -> tambah; material = {...} -> edit (SKU dikunci)
export default function MaterialFormModal({ open, material, onClose, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const isEdit = !!material;

  useEffect(() => {
    if (open) { setForm(material ? { ...material } : EMPTY); setErrors({}); }
  }, [open, material]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const validate = () => {
    const er = {};
    if (!form.sku.trim() || form.sku.trim().length < 2) er.sku = 'SKU wajib diisi (min. 2 karakter)';
    if (!form.name.trim()) er.name = 'Nama wajib diisi';
    if (!form.uom.trim()) er.uom = 'Satuan wajib diisi';
    setErrors(er);
    return Object.keys(er).length === 0;
  };

  const submit = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      if (isEdit) {
        await materialService.update(material.id, {
          name: form.name.trim(), uom: form.uom.trim(), is_active: form.is_active,
        });
      } else {
        await materialService.create({ sku: form.sku.trim(), name: form.name.trim(), uom: form.uom.trim() });
      }
      toast.success(isEdit ? 'Material diperbarui' : 'Material ditambahkan');
      onSaved();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Material Beli' : 'Tambah Material Beli'}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button loading={saving} onClick={submit}>{t('Simpan')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <FormField label={t('SKU')} error={errors.sku}>
          <Input value={form.sku} onChange={set('sku')} disabled={isEdit} placeholder={t('RM-XXX-01')} />
        </FormField>
        <FormField label={t('Nama')} error={errors.name}>
          <Input value={form.name} onChange={set('name')} />
        </FormField>
        <FormField label={t('Satuan')} error={errors.uom}>
          <Input value={form.uom} onChange={set('uom')} placeholder={t('Buah, kg, ml, m²')} />
        </FormField>
        <p className="text-xs text-slate-500">
          {t('Halaman ini khusus material yang dibeli dari supplier. Sub-part dibuat di menu BOM, produk jual di menu Produk Final.')}
        </p>
        {isEdit && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_active} onChange={set('is_active')} /> Aktif
          </label>
        )}
      </div>
    </Modal>
  );
}

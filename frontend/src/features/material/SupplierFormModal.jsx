import { useEffect, useState } from 'react';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input from '../../components/common/Input';
import { supplierService } from '../../services/supplierService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';

const EMPTY = { code: '', name: '', contact: '', payment_term_days: '0', is_active: true };

export default function SupplierFormModal({ open, supplier, onClose, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const isEdit = !!supplier;

  useEffect(() => {
    if (open) { setForm(supplier ? { ...supplier, contact: supplier.contact ?? '', payment_term_days: String(supplier.payment_term_days ?? 0) } : EMPTY); setErrors({}); }
  }, [open, supplier]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const submit = async () => {
    const er = {};
    if (!form.code.trim() || form.code.trim().length < 2) er.code = 'Kode wajib diisi (min. 2 karakter)';
    if (!form.name.trim()) er.name = 'Nama wajib diisi';
    const term = Number(form.payment_term_days);
    if (form.payment_term_days === '' || !Number.isInteger(term) || term < 0 || term > 365) er.payment_term_days = 'Termin 0–365 hari (bilangan bulat)';
    setErrors(er);
    if (Object.keys(er).length) return;
    setSaving(true);
    try {
      const contact = form.contact.trim() || null;
      if (isEdit) {
        await supplierService.update(supplier.id, { name: form.name.trim(), contact, payment_term_days: term, is_active: form.is_active });
      } else {
        await supplierService.create({ code: form.code.trim(), name: form.name.trim(), contact, payment_term_days: term });
      }
      toast.success(isEdit ? 'Supplier diperbarui' : 'Supplier ditambahkan');
      onSaved();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Supplier' : 'Tambah Supplier'}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button loading={saving} onClick={submit}>{t('Simpan')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <FormField label={t('Kode')} error={errors.code}>
          <Input value={form.code} onChange={set('code')} disabled={isEdit} placeholder={t('SUP-XXX')} />
        </FormField>
        <FormField label={t('Nama')} error={errors.name}>
          <Input value={form.name} onChange={set('name')} />
        </FormField>
        <FormField label={t('Kontak')}>
          <Input value={form.contact} onChange={set('contact')} placeholder={t('Telepon / email')} />
        </FormField>
        <FormField label={t('Termin pembayaran (hari)')} error={errors.payment_term_days} hint={t('0 = tunai; 30 = Net 30')}>
          <Input type="number" min="0" max="365" step="1" value={form.payment_term_days} onChange={set('payment_term_days')} />
        </FormField>
        {isEdit && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_active} onChange={set('is_active')} /> {t('Aktif')}
          </label>
        )}
      </div>
    </Modal>
  );
}

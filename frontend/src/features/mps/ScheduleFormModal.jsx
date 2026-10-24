import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input, { Select } from '../../components/common/Input';
import { scheduleService } from '../../services/scheduleService';
import { useMasterStore } from '../../store/masterStore';
import { toast } from '../../store/toastStore';
import { byCategory } from '../../utils/constants';
import { todayISO } from '../../utils/formatters';
import { t } from '../../i18n';

// Tambah jadwal, atau edit (hanya jadwal PLANNED): produk, tanggal, qty, line.
export default function ScheduleFormModal({ open, schedule, defaultDate, onClose, onSaved }) {
  const { materials, lines } = useMasterStore();
  const products = useMemo(() => byCategory(materials, 'FINISHED'), [materials]);
  const [productId, setProductId] = useState('');
  const [lineId, setLineId] = useState('');
  const [date, setDate] = useState(todayISO());
  const [qty, setQty] = useState('');
  const [saving, setSaving] = useState(false);
  const isEdit = !!schedule;

  useEffect(() => {
    if (!open) return;
    setProductId(schedule ? String(schedule.product_id) : '');
    setLineId(schedule ? String(schedule.production_line_id) : '');
    setDate(schedule ? schedule.production_date : (defaultDate ?? todayISO()));
    setQty(schedule ? String(schedule.target_qty) : '');
  }, [open, schedule, defaultDate]);

  // Line default = line aktif pertama (sama dengan aturan server)
  const effectiveLine = lineId || String(lines[0]?.id ?? '');

  const submit = async () => {
    if (!productId) return toast.error('Pilih produk');
    if (!date) return toast.error('Tanggal wajib diisi');
    if (!Number.isInteger(Number(qty)) || Number(qty) <= 0) return toast.error('Target harus bilangan bulat > 0');
    setSaving(true);
    try {
      const body = { production_date: date, target_qty: Number(qty), product_id: Number(productId) };
      if (effectiveLine) body.production_line_id = Number(effectiveLine);
      if (isEdit) await scheduleService.update(schedule.id, body);
      else await scheduleService.create(body);
      toast.success(isEdit ? 'Jadwal diperbarui' : 'Jadwal ditambahkan');
      onSaved();
    } catch (e) { toast.error(e.message); } // 422: BOM produk tidak lengkap / siklus
    finally { setSaving(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? t('Edit Jadwal · {batch}', { batch: schedule.batch_code }) : t('Tambah Jadwal Produksi')}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button loading={saving} onClick={submit}>{t('Simpan')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <FormField label={t('Produk Final')}
          hint={products.length === 0 ? undefined : 'Hanya Produk Final dengan BOM lengkap yang dapat dijadwalkan.'}
          error={products.length === 0 ? 'Belum ada produk final aktif.' : undefined}>
          <Select value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">{t('Pilih produk…')}</option>
            {products.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.sku})</option>)}
          </Select>
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t('Tanggal produksi')}>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </FormField>
          <FormField label={t('Target (unit)')}>
            <Input type="number" min="1" step="1" value={qty} onChange={(e) => setQty(e.target.value)} />
          </FormField>
        </div>
        <FormField label={t('Production line')}>
          <Select value={effectiveLine} onChange={(e) => setLineId(e.target.value)}>
            {lines.map((l) => <option key={l.id} value={l.id}>{l.code} · {l.name}</option>)}
          </Select>
        </FormField>
        {products.length === 0 && (
          <Link to="/products" className="text-sm font-semibold text-primary-700 hover:underline">{t('Buat produk final')}</Link>
        )}
      </div>
    </Modal>
  );
}

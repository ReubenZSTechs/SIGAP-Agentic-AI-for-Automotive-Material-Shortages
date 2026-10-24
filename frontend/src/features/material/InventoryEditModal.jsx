import { useEffect, useState } from 'react';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input, { Select } from '../../components/common/Input';
import { inventoryService } from '../../services/inventoryService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';

// row = baris inventory -> edit; row = null -> atur stok awal material yang belum punya stok (pilih dari `candidates`).
export default function InventoryEditModal({ open, row, candidates = [], onClose, onSaved }) {
  const [materialId, setMaterialId] = useState('');
  const [onHand, setOnHand] = useState('');
  const [safety, setSafety] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMaterialId(row ? String(row.material_id) : '');
    setOnHand(row ? String(row.on_hand) : '0');
    setSafety(row ? String(row.safety_stock) : '0');
  }, [open, row]);

  const submit = async () => {
    if (!materialId) return toast.error('Pilih material');
    if (onHand === '' || Number(onHand) < 0 || safety === '' || Number(safety) < 0) {
      return toast.error('Stok fisik dan safety stock harus ≥ 0');
    }
    setSaving(true);
    try {
      await inventoryService.update(Number(materialId), {
        on_hand: Number(onHand), safety_stock: Number(safety),
      });
      toast.success('Stok diperbarui');
      onSaved();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };

  return (
    <Modal open={open} onClose={onClose}
      title={row ? t('Edit Stok · {name}', { name: row.name }) : t('Atur Stok Material')}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t('Batal')}</Button>
          <Button loading={saving} onClick={submit}>{t('Simpan')}</Button>
        </>
      )}>
      <div className="space-y-3">
        {!row && (
          <FormField label={t('Material')} hint={t('Hanya material beli yang belum memiliki data stok.')}>
            <Select value={materialId} onChange={(e) => setMaterialId(e.target.value)}>
              <option value="">{t('Pilih material…')}</option>
              {candidates.map((m) => <option key={m.id} value={m.id}>{m.sku} · {m.name}</option>)}
            </Select>
          </FormField>
        )}
        <FormField label={t('Stok Fisik (on hand)')} hint={row ? 'Perubahan dicatat sebagai penyesuaian stok.' : undefined}>
          <Input type="number" min="0" step="any" value={onHand} onChange={(e) => setOnHand(e.target.value)} />
        </FormField>
        <FormField label={t('Safety Stock')}>
          <Input type="number" min="0" step="any" value={safety} onChange={(e) => setSafety(e.target.value)} />
        </FormField>
      </div>
    </Modal>
  );
}

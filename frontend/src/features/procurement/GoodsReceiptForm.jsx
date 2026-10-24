import { useState } from 'react';
import Button from '../../components/common/Button';
import { purchaseOrderService } from '../../services/purchaseOrderService';
import { toast } from '../../store/toastStore';
import { formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

export default function GoodsReceiptForm({ po, onDone }) {
  const remaining = (i) => Math.max(0, i.qty_ordered - i.qty_received);
  const defaults = () => Object.fromEntries(po.items.map((i) => [i.id, remaining(i)]));
  const [qty, setQty] = useState(defaults); // default = sisa
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    for (const i of po.items) {
      if (Number(qty[i.id]) > remaining(i)) return toast.error(t('Qty {name} melebihi sisa pesanan', { name: i.name }));
    }
    const items = po.items
      .map((i) => ({ po_item_id: i.id, qty_received: Number(qty[i.id]) }))
      .filter((r) => r.qty_received > 0);
    if (!items.length) return toast.error('Isi minimal satu qty penerimaan');
    setSaving(true);
    try {
      const result = await purchaseOrderService.receive(po.id, items); // {po_status, changes[]}
      toast.success('Penerimaan barang tersimpan, stok diperbarui');
      onDone(result);
    } catch (e) { toast.error(e.message); } // 400 over-receipt / 409 status tidak valid
    finally { setSaving(false); }
  };

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <Button variant="secondary" size="sm" onClick={() => setQty(defaults())}>{t('Terima Semua')}</Button>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-1 font-medium">{t('Material')}</th>
            <th className="py-1 text-right font-medium">{t('Dipesan')}</th>
            <th className="py-1 text-right font-medium">{t('Diterima')}</th>
            <th className="py-1 text-right font-medium">{t('Sisa')}</th>
            <th className="py-1 text-right font-medium">{t('Terima sekarang')}</th>
          </tr>
        </thead>
        <tbody>
          {po.items.map((i) => (
            <tr key={i.id} className="border-t border-slate-100">
              <td className="py-2">{i.name}</td>
              <td className="text-right">{formatQty(i.qty_ordered)} {i.uom}</td>
              <td className="text-right">{formatQty(i.qty_received)}</td>
              <td className="text-right">{formatQty(remaining(i))}</td>
              <td className="text-right">
                <input type="number" min={0} max={remaining(i)} step="any" value={qty[i.id]}
                       aria-label={`Terima ${i.name}`} disabled={remaining(i) === 0}
                       onChange={(e) => setQty({ ...qty, [i.id]: e.target.value })}
                       className="w-24 rounded border border-slate-300 px-2 py-1 text-right disabled:bg-slate-100" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex justify-end">
        <Button loading={saving} onClick={submit}>{t('Simpan Penerimaan')}</Button>
      </div>
    </div>
  );
}

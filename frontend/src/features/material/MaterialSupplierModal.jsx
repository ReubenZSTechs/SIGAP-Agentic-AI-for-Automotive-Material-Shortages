import Icon from '../../components/common/Icon';
import { useMemo, useState } from 'react';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import Badge from '../../components/common/Badge';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import Input, { Select } from '../../components/common/Input';
import { Spinner } from '../../components/common/EmptyState';
import useFetch from '../../hooks/useFetch';
import { materialService } from '../../services/materialService';
import { useMasterStore } from '../../store/masterStore';
import { toast } from '../../store/toastStore';
import { formatLead, formatQty, formatRupiah } from '../../utils/formatters';
import { t } from '../../i18n';

const EMPTY = { supplier_id: '', unit_price: '', lead_time_days: '', moq: '1' };

// Relasi many-to-many Material <-> Supplier (Phase 0)
export default function MaterialSupplierModal({ open, material, onClose }) {
  const suppliers = useMasterStore((s) => s.suppliers);
  const { data: links, loading, reload } = useFetch(
    () => (open && material ? materialService.listSuppliers(material.id) : Promise.resolve([])),
    [open, material?.id],
  );
  const [adding, setAdding] = useState(EMPTY);
  const [editing, setEditing] = useState(null); // { supplier_id, unit_price, lead_time_days, moq }
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);

  const available = useMemo(() => {
    const linked = new Set((links ?? []).map((l) => l.supplier_id));
    return suppliers.filter((s) => !linked.has(s.id));
  }, [links, suppliers]);

  const validNums = (f) => Number(f.unit_price) >= 0 && f.unit_price !== ''
    && Number(f.lead_time_days) >= 0 && f.lead_time_days !== '' && Number(f.moq) > 0;

  const add = async () => {
    if (!adding.supplier_id) return toast.error('Pilih supplier');
    if (!validNums(adding)) return toast.error('Harga ≥ 0, lead time ≥ 0, MOQ > 0');
    setBusy(true);
    try {
      await materialService.linkSupplier(material.id, {
        supplier_id: Number(adding.supplier_id), unit_price: Number(adding.unit_price),
        lead_time_days: Number(adding.lead_time_days), moq: Number(adding.moq),
      });
      setAdding(EMPTY); reload();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const saveEdit = async () => {
    if (!validNums(editing)) return toast.error('Harga ≥ 0, lead time ≥ 0, MOQ > 0');
    setBusy(true);
    try {
      await materialService.updateLink(material.id, editing.supplier_id, {
        unit_price: Number(editing.unit_price), lead_time_days: Number(editing.lead_time_days),
        moq: Number(editing.moq),
      });
      setEditing(null); reload();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await materialService.unlinkSupplier(material.id, deleting.supplier_id);
      setDeleting(null); reload();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const onKey = (e) => {                           // Enter = simpan, Esc = batal (inline edit)
    if (e.key === 'Enter') saveEdit();
    if (e.key === 'Escape') { e.stopPropagation(); setEditing(null); }
  };
  const cell = 'w-24 py-1 text-right';

  return (
    <>
      <Modal open={open} onClose={onClose} size="lg"
             title={material ? t('Supplier untuk {name}', { name: material.name }) : t('Supplier')}
             footer={<Button variant="secondary" onClick={onClose}>{t('Tutup')}</Button>}>
        {loading ? <Spinner /> : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <th className="px-2 py-2 text-left font-medium">{t('Supplier')}</th>
                <th className="px-2 py-2 text-right font-medium">{t('Harga/Unit')}</th>
                <th className="px-2 py-2 text-right font-medium">{t('Lead Time')}</th>
                <th className="px-2 py-2 text-right font-medium">MOQ</th>
                <th className="px-2 py-2 text-left font-medium">{t('Label')}</th>
                <th className="px-2 py-2 text-right font-medium">{t('Aksi')}</th>
              </tr>
            </thead>
            <tbody>
              {(links ?? []).length === 0 && (
                <tr><td colSpan={6} className="px-2 py-6 text-center text-slate-500">
                  {t('Belum ada supplier — tambahkan di bawah.')}</td></tr>
              )}
              {(links ?? []).map((l) => {
                const isEdit = editing?.supplier_id === l.supplier_id;
                return (
                  <tr key={l.supplier_id} className="border-b border-slate-100 last:border-0">
                    <td className="px-2 py-2 font-medium">{l.supplier_name}</td>
                    {isEdit ? (
                      <>
                        <td className="px-2 text-right"><Input type="number" min="0" className={cell} autoFocus onKeyDown={onKey}
                          value={editing.unit_price} onChange={(e) => setEditing({ ...editing, unit_price: e.target.value })} /></td>
                        <td className="px-2 text-right"><Input type="number" min="0" className={cell} onKeyDown={onKey}
                          value={editing.lead_time_days} onChange={(e) => setEditing({ ...editing, lead_time_days: e.target.value })} /></td>
                        <td className="px-2 text-right"><Input type="number" min="0" step="any" className={cell} onKeyDown={onKey}
                          value={editing.moq} onChange={(e) => setEditing({ ...editing, moq: e.target.value })} /></td>
                      </>
                    ) : (
                      <>
                        <td className="px-2 text-right">{formatRupiah(l.unit_price)}</td>
                        <td className="px-2 text-right">{formatLead(l.lead_time_days)}</td>
                        <td className="px-2 text-right">{formatQty(l.moq)}</td>
                      </>
                    )}
                    <td className="px-2">
                      <span className="flex flex-wrap gap-1">
                        {l.is_cheapest && <Badge tone="green">{t('Termurah')}</Badge>}
                        {l.is_fastest && <Badge tone="indigo">{t('Tercepat')}</Badge>}
                        {!l.is_active && <Badge tone="slate">{t('Nonaktif')}</Badge>}
                      </span>
                    </td>
                    <td className="px-2 text-right">
                      {isEdit ? (
                        <span className="inline-flex gap-1">
                          <Button size="sm" loading={busy} onClick={saveEdit}>{t('Simpan')}</Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>{t('Batal')}</Button>
                        </span>
                      ) : (
                        <span className="inline-flex gap-1">
                          <Button size="sm" variant="ghost" aria-label={t('Edit relasi')}
                            onClick={() => setEditing({ supplier_id: l.supplier_id, unit_price: l.unit_price,
                              lead_time_days: l.lead_time_days, moq: l.moq })}><Icon name="edit" /></Button>
                          <Button size="sm" variant="ghost" className="text-red-600" aria-label={t('Hapus relasi')}
                            onClick={() => setDeleting(l)}><Icon name="trash" /></Button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <div className="mt-4 grid grid-cols-[1fr_7rem_6rem_5rem_auto] items-end gap-2 border-t border-slate-200 pt-4">
          <Select value={adding.supplier_id} onChange={(e) => setAdding({ ...adding, supplier_id: e.target.value })}>
            <option value="">{t('Pilih supplier…')}</option>
            {available.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
          <Input type="number" min="0" placeholder={t('Harga')} value={adding.unit_price}
                 onChange={(e) => setAdding({ ...adding, unit_price: e.target.value })} />
          <Input type="number" min="0" placeholder={t('Lead (hari)')} value={adding.lead_time_days}
                 onChange={(e) => setAdding({ ...adding, lead_time_days: e.target.value })} />
          <Input type="number" min="0" step="any" placeholder={t('MOQ')} value={adding.moq}
                 onChange={(e) => setAdding({ ...adding, moq: e.target.value })} />
          <Button loading={busy} onClick={add}><Icon name="plus" /> {t('Tambah')}</Button>
        </div>
      </Modal>

      <ConfirmDialog open={!!deleting} loading={busy}
        message={t('Hapus relasi dengan {name}?', { name: deleting?.supplier_name })}
        onConfirm={remove} onCancel={() => setDeleting(null)} />
    </>
  );
}

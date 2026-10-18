import Icon from '../../components/common/Icon';
import { useEffect, useMemo, useState } from 'react';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import FormField from '../../components/common/FormField';
import Input, { Select, Textarea } from '../../components/common/Input';
import useFetch from '../../hooks/useFetch';
import { inventoryService } from '../../services/inventoryService';
import { materialService } from '../../services/materialService';
import { useMasterStore } from '../../store/masterStore';
import { byCategory } from '../../utils/constants';
import { formatQty, formatRupiah, todayISO } from '../../utils/formatters';

const newRow = () => ({ material_id: '', qty: '', unit_price: '', needed_by: '', price_touched: false });
const toRow = (i) => ({ material_id: String(i.material_id), qty: String(i.qty_ordered), unit_price: String(i.unit_price),
  needed_by: i.needed_by_date ?? '', price_touched: true });

// Form PO mandiri. Item HARUS dari master material beli (Goods Receipt memperbarui inventory lewat material_id).
export default function ManualPoForm({ initial, saving, onSubmit }) {
  const { materials, suppliers } = useMasterStore();
  const stock = useFetch(() => inventoryService.list(), []); // tersedia / dipesan / safety per material
  const [h, setH] = useState({ supplier_id: initial ? String(initial.supplier_id) : '', po_date: initial?.po_date ?? todayISO(), notes: initial?.notes ?? '' });
  const [rows, setRows] = useState(initial?.items?.length ? initial.items.map(toRow) : [newRow()]);
  const [links, setLinks] = useState({}); // material_id -> relasi material–supplier (cache)

  const buyable = useMemo(() => byCategory(materials, 'PURCHASED'), [materials]);
  const supplier = suppliers.find((s) => s.id === Number(h.supplier_id));
  const linkOf = (r) => links[r.material_id]?.find((l) => l.supplier_id === Number(h.supplier_id) && l.is_active);
  const patchRow = (i, p) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...p } : r)));

  const loadLinks = async (id) => {
    if (!id || links[id]) return;
    const ls = await materialService.listSuppliers(id);
    setLinks((p) => ({ ...p, [id]: ls }));
  };
  useEffect(() => { rows.forEach((r) => loadLinks(r.material_id)); /* eslint-disable-next-line */ }, []); // mode edit

  const pickMaterial = async (i, id) => {
    patchRow(i, { material_id: id, price_touched: false });
    await loadLinks(id);
  };

  // Harga default dari relasi material–supplier, selama user belum mengubahnya
  useEffect(() => {
    setRows((rs) => rs.map((r) => {
      const l = linkOf(r);
      return !r.price_touched && l ? { ...r, unit_price: String(l.unit_price) } : r;
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links, h.supplier_id]);

  const errors = useMemo(() => {
    const er = [];
    if (!h.supplier_id) er.push('Pilih supplier');
    if (!h.po_date) er.push('Tanggal PO wajib diisi');
    if (rows.some((r) => !r.material_id)) er.push('Pilih material pada setiap baris');
    rows.forEach((r, i) => {
      if (!(Number(r.qty) > 0)) er.push(`Baris ${i + 1}: qty harus > 0`);
      if (r.unit_price === '' || !Number.isInteger(Number(r.unit_price)) || Number(r.unit_price) < 0) er.push(`Baris ${i + 1}: harga bilangan bulat ≥ 0`);
      if (r.needed_by && h.po_date && r.needed_by < h.po_date) er.push(`Baris ${i + 1}: tanggal kebutuhan sebelum tanggal PO`);
    });
    return er;
  }, [h, rows]);

  const total = rows.reduce((a, r) => a + Math.round((Number(r.qty) || 0) * (Number(r.unit_price) || 0)), 0);
  const payload = () => ({
    supplier_id: Number(h.supplier_id), po_date: h.po_date, notes: h.notes.trim() || null,
    items: rows.map((r) => ({ material_id: Number(r.material_id), qty_ordered: Number(r.qty),
      unit_price: Number(r.unit_price), needed_by_date: r.needed_by || null })),
  });

  return (
    <div className="space-y-4">
      <Card title="Header">
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Supplier*">
            <Select value={h.supplier_id} onChange={(e) => setH({ ...h, supplier_id: e.target.value })}>
              <option value="">Pilih supplier…</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name} — {s.payment_term_days > 0 ? `Net ${s.payment_term_days}` : 'Tunai'}</option>)}
            </Select>
          </FormField>
          <FormField label="Tanggal PO*">
            <Input type="date" value={h.po_date} onChange={(e) => setH({ ...h, po_date: e.target.value })} />
          </FormField>
          <FormField label="Catatan" className="sm:col-span-2">
            <Textarea rows={2} maxLength={500} value={h.notes} onChange={(e) => setH({ ...h, notes: e.target.value })} />
          </FormField>
        </div>
      </Card>

      <Card title="Item" padded={false}
        actions={<Button size="sm" variant="secondary" onClick={() => setRows((rs) => [...rs, newRow()])}><Icon name="plus" /> Tambah item</Button>}>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2 font-medium">Material*</th><th className="py-2 font-medium">Qty*</th><th className="py-2 font-medium">Sat.</th>
              <th className="py-2 font-medium">Harga satuan*</th><th className="py-2 font-medium">Tgl kebutuhan</th>
              <th className="py-2 text-right font-medium">Subtotal</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const m = materials.find((x) => x.id === Number(r.material_id));
              const l = linkOf(r);
              const st = stock.data?.find((x) => x.material_id === Number(r.material_id));
              const taken = new Set(rows.filter((_, k) => k !== i).map((x) => Number(x.material_id)));
              return [
                <tr key={`r${i}`} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-2">
                    <Select aria-label={`Material baris ${i + 1}`} value={r.material_id} onChange={(e) => pickMaterial(i, e.target.value)}>
                      <option value="">Pilih material…</option>
                      {buyable.filter((b) => !taken.has(b.id)).map((b) => <option key={b.id} value={b.id}>{b.sku} · {b.name}</option>)}
                    </Select>
                  </td>
                  <td className="py-2"><Input aria-label={`Qty baris ${i + 1}`} type="number" min="0" step="any" className="w-24" value={r.qty} onChange={(e) => patchRow(i, { qty: e.target.value })} /></td>
                  <td className="py-2 text-slate-600">{m?.uom ?? '—'}</td>
                  <td className="py-2"><Input aria-label={`Harga baris ${i + 1}`} type="number" min="0" step="1" className="w-32" value={r.unit_price}
                    onChange={(e) => patchRow(i, { unit_price: e.target.value, price_touched: true })} /></td>
                  <td className="py-2"><Input aria-label={`Tanggal kebutuhan baris ${i + 1}`} type="date" className="w-40" value={r.needed_by} onChange={(e) => patchRow(i, { needed_by: e.target.value })} /></td>
                  <td className="py-2 text-right">{formatRupiah(Math.round((Number(r.qty) || 0) * (Number(r.unit_price) || 0)))}</td>
                  <td className="py-2 pr-3 text-right">
                    {rows.length > 1 && <Button size="sm" variant="ghost" aria-label={`Hapus baris ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}><Icon name="trash" /></Button>}
                  </td>
                </tr>,
                <tr key={`i${i}`}>
                  <td colSpan={7} className="px-3 pb-2">
                    {l && <p className="text-xs text-slate-500">Lead time {l.lead_time_days} hari (supplier ini)</p>}
                    {r.material_id && supplier && !l && (
                      <p className="flex items-center gap-1 text-xs text-amber-700"><Icon name="alert" className="h-3.5 w-3.5" /> Supplier belum terdaftar untuk material ini — tetap bisa dipesan.</p>
                    )}
                    {st && <p className="text-xs text-slate-500">Tersedia {formatQty(st.available)} · Dipesan {formatQty(st.on_order)} · Safety {formatQty(st.safety_stock)}</p>}
                  </td>
                </tr>,
              ];
            })}
          </tbody>
        </table>
        <div className="border-t border-slate-100 px-3 py-2 text-right text-sm">Total <b>{formatRupiah(total)}</b></div>
      </Card>

      {errors.length > 0 && (
        <ul className="list-inside list-disc rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {errors.slice(0, 5).map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" disabled={errors.length > 0} loading={saving === 'draft'} onClick={() => onSubmit(payload(), false)}>Simpan Draft</Button>
        <Button disabled={errors.length > 0} loading={saving === 'submit'} onClick={() => onSubmit(payload(), true)}>Simpan & Submit</Button>
      </div>
    </div>
  );
}

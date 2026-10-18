import { useEffect, useMemo, useState } from 'react';
import Modal from '../../components/common/Modal';
import Button from '../../components/common/Button';
import FormField from '../../components/common/FormField';
import Input, { Select } from '../../components/common/Input';
import Tabs from '../../components/common/Tabs';
import { bomService } from '../../services/bomService';
import { useMasterStore } from '../../store/masterStore';
import { toast } from '../../store/toastStore';
import { byCategory } from '../../utils/constants';

const NEW_SUB = { sku: '', name: '', uom: 'Set' };

// form: { mode:'add', parent, existingChildIds } | { mode:'edit', node }
export default function BomItemFormModal({ open, form, onClose, onSaved }) {
  const { materials, ensureLoaded } = useMasterStore();
  const [kind, setKind] = useState('purchased');   // 'purchased' | 'subpart'
  const [subMode, setSubMode] = useState('new');   // 'new' | 'existing'
  const [childId, setChildId] = useState('');      // material beli ATAU sub-part yang sudah ada
  const [sub, setSub] = useState(NEW_SUB);         // sub-part baru (sku, name, uom) / edit nama sub-part
  const [qty, setQty] = useState('1');
  const [saving, setSaving] = useState(false);
  const isEdit = form?.mode === 'edit';
  const editMat = isEdit ? form.node.material : null;
  const editingSubPart = editMat?.category === 'SUB_PART';

  useEffect(() => {
    if (!open || !form) return;
    setKind('purchased'); setSubMode('new'); setChildId('');
    if (isEdit) {
      setQty(String(form.node.qty_per_parent));
      setSub({ sku: form.node.material.sku, name: form.node.material.name, uom: form.node.material.uom });
    } else { setQty('1'); setSub(NEW_SUB); }
  }, [open, form, isEdit]);

  // Pilihan dropdown: kecualikan induk sendiri & komponen yang sudah ada. Produk Final tidak bisa jadi komponen.
  const purchased = useMemo(() => {
    if (!form || isEdit) return [];
    const skip = new Set(form.existingChildIds);
    return byCategory(materials, 'PURCHASED').filter((m) => !skip.has(m.id));
  }, [form, isEdit, materials]);
  const existingSubs = useMemo(() => {
    if (!form || isEdit) return [];
    const skip = new Set([form.parent.id, ...form.existingChildIds]);
    return byCategory(materials, 'SUB_PART').filter((m) => !skip.has(m.id));
  }, [form, isEdit, materials]);

  const setSubField = (k) => (e) => setSub({ ...sub, [k]: e.target.value });

  const submit = async () => {
    if (!(Number(qty) > 0)) return toast.error('Qty harus > 0');
    setSaving(true);
    try {
      if (isEdit) {
        if (editingSubPart) {
          if (!sub.name.trim() || !sub.uom.trim()) { toast.error('Nama dan satuan sub-part wajib diisi'); return; }
          if (sub.name.trim() !== editMat.name || sub.uom.trim() !== editMat.uom) {
            await bomService.updateSubPart(editMat.id, { name: sub.name.trim(), uom: sub.uom.trim() });
          }
        }
        await bomService.updateItem(form.node.bom_item_id, { qty_per_parent: Number(qty) });
        toast.success('Komponen diperbarui');
      } else if (kind === 'subpart' && subMode === 'new') {
        if (sub.sku.trim().length < 2) { toast.error('SKU sub-part wajib diisi (min. 2 karakter)'); return; }
        if (!sub.name.trim() || !sub.uom.trim()) { toast.error('Nama dan satuan sub-part wajib diisi'); return; }
        await bomService.addSubPart({
          parent_id: form.parent.id, sku: sub.sku.trim(), name: sub.name.trim(),
          uom: sub.uom.trim(), qty_per_parent: Number(qty),
        });
        toast.success('Sub-part dibuat & ditambahkan — tambahkan komponennya dengan tombol tambah (+) di barisnya');
      } else {
        if (!childId) { toast.error(kind === 'purchased' ? 'Pilih material beli' : 'Pilih sub-part'); return; }
        await bomService.addItem({ parent_id: form.parent.id, child_id: Number(childId), qty_per_parent: Number(qty) });
        toast.success('Komponen ditambahkan');
      }
      await ensureLoaded(true);   // nama / sub-part baru langsung muncul di dropdown & halaman lain
      onSaved();
    } catch (e) { toast.error(e.message); } // 409 siklus/duplikat/SKU bentrok tampil apa adanya
    finally { setSaving(false); }
  };

  const title = isEdit ? `Ubah Komponen · ${editMat?.name}` : `Tambah Komponen ke ${form?.parent?.name ?? ''}`;
  const uomLabel = isEdit ? editMat?.uom : (kind === 'purchased'
    ? materials.find((m) => m.id === Number(childId))?.uom
    : (subMode === 'new' ? sub.uom : materials.find((m) => m.id === Number(childId))?.uom));

  return (
    <Modal open={open} onClose={onClose} title={title}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>Batal</Button>
          <Button loading={saving} onClick={submit}>Simpan</Button>
        </>
      )}>
      <div className="space-y-3">
        {!isEdit && (
          <Tabs variant="segmented" value={kind} onChange={(k) => { setKind(k); setChildId(''); }}
                tabs={[{ id: 'purchased', label: 'Material Beli' }, { id: 'subpart', label: 'Sub-part (Made)' }]} />
        )}

        {!isEdit && kind === 'purchased' && (
          <FormField label="Material beli"
            hint={purchased.length === 0 ? 'Tidak ada material beli yang tersedia — tambahkan di menu Material Beli.' : undefined}>
            <Select value={childId} onChange={(e) => setChildId(e.target.value)}>
              <option value="">Pilih material…</option>
              {purchased.map((m) => <option key={m.id} value={m.id}>{m.sku} · {m.name} ({m.uom})</option>)}
            </Select>
          </FormField>
        )}

        {!isEdit && kind === 'subpart' && (
          <>
            <Tabs variant="segmented" value={subMode} onChange={(m) => { setSubMode(m); setChildId(''); }}
                  tabs={[{ id: 'new', label: 'Buat sub-part baru' }, { id: 'existing', label: 'Pakai yang sudah ada' }]} />
            {subMode === 'existing' ? (
              <FormField label="Sub-part"
                hint={existingSubs.length === 0 ? 'Belum ada sub-part lain — pilih "Buat sub-part baru".' : undefined}>
                <Select value={childId} onChange={(e) => setChildId(e.target.value)}>
                  <option value="">Pilih sub-part…</option>
                  {existingSubs.map((m) => <option key={m.id} value={m.id}>{m.sku} · {m.name} ({m.uom})</option>)}
                </Select>
              </FormField>
            ) : null}
          </>
        )}

        {((!isEdit && kind === 'subpart' && subMode === 'new') || editingSubPart) && (
          <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
            {!isEdit && (
              <FormField label="SKU sub-part">
                <Input value={sub.sku} onChange={setSubField('sku')} placeholder="SA-XXX-01" />
              </FormField>
            )}
            <div className="grid grid-cols-[1fr_6rem] gap-3">
              <FormField label="Nama sub-part"><Input value={sub.name} onChange={setSubField('name')} /></FormField>
              <FormField label="Satuan"><Input value={sub.uom} onChange={setSubField('uom')} /></FormField>
            </div>
            {!isEdit && (
              <p className="text-xs text-slate-500">
                Sub-part dibuat di master dan langsung dipasang ke induk ini. Setelah itu, tambahkan material
                penyusunnya lewat tombol tambah (+) di baris sub-part.
              </p>
            )}
          </div>
        )}

        <FormField label={`Qty per induk${uomLabel ? ` (${uomLabel})` : ''}`}>
          <Input type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} />
        </FormField>
      </div>
    </Modal>
  );
}

import Icon from '../../components/common/Icon';
import { useState } from 'react';
import BomNode from './BomNode';
import BomItemFormModal from './BomItemFormModal';
import Card from '../../components/common/Card';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import EmptyState, { Spinner } from '../../components/common/EmptyState';
import Button from '../../components/common/Button';
import CategoryBadge from '../../components/common/CategoryBadge';
import useFetch from '../../hooks/useFetch';
import { bomService } from '../../services/bomService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';

export default function BomTree({ productId }) {
  const { data: tree, loading, error, reload } = useFetch(() => bomService.tree(productId), [productId]);
  const [form, setForm] = useState(null);       // { mode: 'add'|'edit', parent?, node?, existingChildIds? }
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);

  if (loading) return <Spinner />;
  if (error) return <EmptyState title={t('Gagal memuat BOM')} description={error.message} />;

  const remove = async () => {
    setBusy(true);
    try {
      await bomService.removeItem(deleting.bom_item_id);
      toast.success('Komponen dihapus');
      setDeleting(null); reload();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const onAdd = (parent, children) =>
    setForm({ mode: 'add', parent, existingChildIds: children.map((c) => c.material.id) });

  return (
    <Card padded={false}>
      <div className="p-3">
        <p className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <CategoryBadge category="FINISHED" /> produk jual
          <CategoryBadge category="SUB_PART" /> dirakit internal (bisa punya komponen)
          <CategoryBadge category="PURCHASED" /> dibeli dari supplier
          <span className="inline-flex flex-wrap items-center gap-1">{t('Arahkan kursor ke baris untuk')} <Icon name="plus" className="h-3.5 w-3.5" /> {t('tambah komponen,')} <Icon name="edit" className="h-3.5 w-3.5" /> {t('ubah,')} <Icon name="trash" className="h-3.5 w-3.5" /> {t('hapus.')}</span>
        </p>
        {tree.children.length === 0 && (
          <EmptyState title={t('Belum ada komponen')}
            description={t('Tambahkan material beli atau sub-part (Made) untuk membentuk struktur.')}
            action={<Button onClick={() => onAdd(tree.material, [])}><Icon name="plus" /> {t('Komponen')}</Button>} />
        )}
        <ul><BomNode node={tree} onAdd={onAdd} onEdit={(node) => setForm({ mode: 'edit', node })}
                     onDelete={setDeleting} /></ul>
      </div>

      <BomItemFormModal open={!!form} form={form} onClose={() => setForm(null)}
        onSaved={() => { setForm(null); reload(); }} />
      <ConfirmDialog open={!!deleting} loading={busy}
        message={deleting ? t('Hapus "{name}" dari BOM?', { name: deleting.material.name }) + (
          deleting.material.category === 'SUB_PART' ? ` ${t('Sub-part tetap tersimpan di master dan dapat dipakai di BOM lain.')}` : '') : ''}
        onConfirm={remove} onCancel={() => setDeleting(null)} />
    </Card>
  );
}

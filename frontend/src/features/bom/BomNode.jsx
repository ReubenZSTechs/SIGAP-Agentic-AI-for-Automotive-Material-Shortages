import Icon from '../../components/common/Icon';
import { useState } from 'react';
import CategoryBadge from '../../components/common/CategoryBadge';
import { formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

export default function BomNode({ node, onAdd, onEdit, onDelete }) {
  const [open, setOpen] = useState(true);
  const { material, qty_per_parent, children = [], bom_item_id } = node;
  const isMake = material.procurement_type === 'MAKE';
  const isRoot = bom_item_id == null; // root tidak punya induk

  return (
    <li>
      <div className="group flex items-center gap-2 rounded-lg px-2 py-2 transition-colors hover:bg-primary-50/60">
        <button
          className="flex w-5 justify-center text-slate-400 hover:text-slate-700"
          onClick={() => setOpen(!open)}
          disabled={!children.length}
          aria-label={open ? 'Tutup' : 'Buka'}
        >
          {children.length ? <Icon name={open ? 'chevronDown' : 'chevronRight'} className="h-4 w-4" /> : null}
        </button>
        <span className="font-semibold text-slate-900">{material.name}</span>
        <CategoryBadge category={material.category} />
        {!isRoot && (
          <span className="ml-auto text-sm text-slate-500">
            × {formatQty(qty_per_parent)} {material.uom}
          </span>
        )}
        <span className={`flex gap-0.5 text-sm opacity-0 focus-within:opacity-100 group-hover:opacity-100 ${isRoot ? 'ml-auto' : ''}`}>
          {isMake && <button onClick={() => onAdd(material, children)} aria-label={t('Tambah komponen')} title={t('Tambah komponen')} className="rounded-md p-1.5 text-slate-500 hover:bg-primary-100 hover:text-primary-700"><Icon name="plus" /></button>}
          {!isRoot && <button onClick={() => onEdit(node)} aria-label={t('Ubah qty')} title={t('Ubah qty')} className="rounded-md p-1.5 text-slate-500 hover:bg-primary-100 hover:text-primary-700"><Icon name="edit" /></button>}
          {!isRoot && <button onClick={() => onDelete(node)} aria-label={t('Hapus')} title={t('Hapus')} className="rounded-md p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600"><Icon name="trash" /></button>}
        </span>
      </div>
      {open && children.length > 0 && (
        <ul className="ml-[18px] border-l border-slate-200 pl-3">
          {children.map((c) => (
            <BomNode key={c.bom_item_id} node={c} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
          ))}
        </ul>
      )}
    </li>
  );
}

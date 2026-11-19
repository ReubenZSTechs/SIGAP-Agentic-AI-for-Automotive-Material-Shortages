import Badge from './Badge';
import { CATEGORY } from '../../utils/constants';

// Pembeda visual: Produk Final / Sub-part (Made) / Material Beli.
export default function CategoryBadge({ category, long = false }) {
  const c = CATEGORY[category] ?? { label: category, short: category, tone: 'slate' };
  return <Badge tone={c.tone}>{long ? c.label : c.short}</Badge>;
}

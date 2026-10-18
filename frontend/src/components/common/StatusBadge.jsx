import Badge from './Badge';
import { STOCK_STATUS } from '../../utils/constants';

// Status = titik warna + teks (tidak mengandalkan warna saja).
export default function StatusBadge({ status }) {
  const s = STOCK_STATUS[status] ?? { label: status, tone: 'slate' };
  return (
    <Badge tone={s.tone}>
      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {s.label}
    </Badge>
  );
}

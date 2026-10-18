import Badge from './Badge';
import { PO_STATUS } from '../../utils/constants';

export default function PoStatusBadge({ status }) {
  const s = PO_STATUS[status] ?? { label: status, tone: 'slate' };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

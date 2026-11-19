import Badge from '../../components/common/Badge';
import { t } from '../../i18n';

// Status = titik + teks (tidak mengandalkan warna saja). meta: { label, tone }
export default function StateBadge({ meta }) {
  return (
    <Badge tone={meta.tone}>
      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {t(meta.label)}
    </Badge>
  );
}

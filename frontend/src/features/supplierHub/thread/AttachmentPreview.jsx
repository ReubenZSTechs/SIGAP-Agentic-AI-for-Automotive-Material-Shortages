import { useNavigate } from 'react-router-dom';
import Button from '../../../components/common/Button';
import Icon from '../../../components/common/Icon';
import Modal from '../../../components/common/Modal';
import FilePreview from './FilePreview';
import { hubService } from '../../../services/hubService';
import { purchaseOrderService } from '../../../services/purchaseOrderService';
import { t } from '../../../i18n';

// Pratinjau lampiran supplier atau PDF PO final dari agent (dibuka dari PO-nya).
export default function AttachmentPreview({ attachment: a, onClose }) {
  const navigate = useNavigate();
  if (!a) return null;
  const url = a.outbound ? purchaseOrderService.revisionPdfUrl(a.po_id, a.revision_id) : hubService.attachmentFileUrl(a.doc_id);
  return (
    <Modal open onClose={onClose} size="lg" title={a.name}
      footer={(
        <>
          <a href={url} download={a.name} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-white px-3.5 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
            <Icon name="download" /> Unduh
          </a>
          {a.outbound && <Button onClick={() => navigate(`/purchase-orders/${a.po_id}`)}><Icon name="file" /> {t('Buka PO')}</Button>}
        </>
      )}>
      <FilePreview url={url} kind={a.kind} name={a.name} />
    </Modal>
  );
}

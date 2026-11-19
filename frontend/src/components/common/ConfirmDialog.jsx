import Button from './Button';
import Modal from './Modal';
import { t, tx } from '../../i18n';

export default function ConfirmDialog({
  open, message, onConfirm, onCancel, loading = false,
  confirmLabel = 'Ya, lanjutkan', variant = 'danger', title = 'Konfirmasi',
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel} layer={60}
      footer={(
        <>
          <Button variant="secondary" onClick={onCancel}>{t('Batal')}</Button>
          <Button variant={variant} loading={loading} onClick={onConfirm}>{tx(confirmLabel)}</Button>
        </>
      )}>
      <p className="text-sm text-slate-700">{tx(message)}</p>
    </Modal>
  );
}

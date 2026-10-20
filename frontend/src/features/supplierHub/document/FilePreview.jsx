import { useState } from 'react';
import Icon from '../../../components/common/Icon';

// File asli dari supplier: gambar ditampilkan langsung, PDF di iframe, selain itu tautan unduh.
export default function FilePreview({ url, kind, name, tall = false }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg bg-slate-50 py-12 text-center text-sm text-slate-500">
        <Icon name="alert" className="h-6 w-6 text-amber-600" />
        File tidak tersimpan di server (terlalu besar atau gagal diunduh dari Telegram). Minta ulang ke supplier.
      </div>
    );
  }
  if (kind === 'image') {
    return <img src={url} alt={`Lampiran ${name}`} onError={() => setFailed(true)} className="mx-auto max-h-[70vh] rounded-lg ring-1 ring-slate-200" />;
  }
  if (kind === 'pdf') {
    return <iframe src={url} title={name} className={`w-full rounded-lg ring-1 ring-slate-200 ${tall ? 'h-[75vh]' : 'h-[60vh]'}`} />;
  }
  return (
    <a href={url} download={name} className="flex items-center justify-center gap-2 rounded-lg bg-slate-50 py-12 text-sm font-medium text-primary-700 hover:underline">
      <Icon name="download" /> Unduh {name}
    </a>
  );
}

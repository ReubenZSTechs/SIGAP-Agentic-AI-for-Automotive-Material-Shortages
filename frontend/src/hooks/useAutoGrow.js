import { useLayoutEffect, useRef } from 'react';

// Textarea ikut memanjang sesuai isinya sampai `maxPx`, lalu bergulir. Kembali satu baris saat teks dikosongkan.
export default function useAutoGrow(value, maxPx = 192) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, maxPx);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > maxPx ? 'auto' : 'hidden';
  }, [value, maxPx]);
  return ref;
}

import { useEffect, useRef } from 'react';

// Memanggil fn tiap `ms` milidetik; dilewati saat tab tersembunyi. Jalur upgrade: ganti dengan SSE.
export default function usePolling(fn, ms, enabled = true) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!enabled) return undefined;
    const id = setInterval(() => { if (!document.hidden) ref.current(); }, ms);
    return () => clearInterval(id);
  }, [ms, enabled]);
}

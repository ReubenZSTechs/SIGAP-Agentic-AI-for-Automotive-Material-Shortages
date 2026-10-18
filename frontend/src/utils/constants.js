// Label tampilan (nilai enum mengikuti backend)
export const STOCK_STATUS = {
  CRITICAL: { label: 'Critical', tone: 'red' },
  WARNING: { label: 'Warning', tone: 'amber' },
  SAFE: { label: 'Aman', tone: 'green' },
};

export const PO_STATUS = {
  DRAFT: { label: 'Draft', tone: 'slate' },
  PENDING_APPROVAL: { label: 'Menunggu Approval', tone: 'amber' },
  APPROVED: { label: 'Disetujui', tone: 'violet' },
  REJECTED: { label: 'Ditolak', tone: 'red' },
  ISSUED: { label: 'Diterbitkan', tone: 'indigo' },
  PARTIALLY_RECEIVED: { label: 'Diterima Sebagian', tone: 'amber' },
  RECEIVED: { label: 'Diterima', tone: 'green' },
  CANCELLED: { label: 'Dibatalkan', tone: 'red' },
};

export const SCHEDULE_STATUS = {
  PLANNED: { label: 'Planned', tone: 'indigo' },
  IN_PROGRESS: { label: 'In Progress', tone: 'amber' },
  COMPLETED: { label: 'Completed', tone: 'green' },
  CANCELLED: { label: 'Cancelled', tone: 'slate' },
};

// Aksi status jadwal (urutan & label tombol); transisi valid dikirim server (`allowed_transitions`)
export const SCHEDULE_ACTIONS = {
  IN_PROGRESS: { label: 'Mulai Produksi', variant: 'primary' },
  COMPLETED: { label: 'Selesaikan', variant: 'primary' },
  CANCELLED: { label: 'Batalkan', variant: 'danger' },
};

export const PO_SOURCE = {
  MANUAL: { label: 'Manual PO', tone: 'violet' },
  PLANNING: { label: 'Planning', tone: 'slate' },
};

export const MOVEMENT_TYPE = {
  GOODS_RECEIPT: 'Penerimaan barang',
  ADJUSTMENT: 'Penyesuaian stok',
  PRODUCTION_ISSUE: 'Pemakaian produksi',
};

export const STRATEGIES = [
  { id: 'CHEAPEST', label: 'Termurah' },
  { id: 'FASTEST', label: 'Tercepat' },
  { id: 'BALANCED', label: 'Seimbang' },
];

export const OPEN_PO_STATUSES = ['DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', 'PARTIALLY_RECEIVED'];

// Kategori item (backend: ItemCategory). Procurement type diturunkan di backend.
export const CATEGORY = {
  FINISHED: { label: 'Produk Final', short: 'Final', tone: 'indigo' },
  SUB_PART: { label: 'Sub-part (Made)', short: 'Sub-part', tone: 'violet' },
  PURCHASED: { label: 'Material Beli', short: 'Beli', tone: 'slate' },
};

// Helper filter daftar item dari masterStore.materials
export const byCategory = (items, ...cats) =>
  items.filter((m) => m.is_active && cats.includes(m.category));

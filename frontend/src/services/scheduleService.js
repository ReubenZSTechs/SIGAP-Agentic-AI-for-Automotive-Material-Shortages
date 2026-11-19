import api from './api';

export const scheduleService = {
  list: (params) => api.get('/schedules', { params }),
  create: (body) => api.post('/schedules', body), // {product_id, production_date, target_qty, production_line_id?}
  // Edit / reschedule — hanya jadwal PLANNED: production_date | target_qty | product_id | production_line_id
  update: (id, body) => api.patch(`/schedules/${id}`, body),
  // Satu-satunya jalur ubah status: IN_PROGRESS (potong stok) | COMPLETED | CANCELLED
  setStatus: (id, status) => api.patch(`/schedules/${id}/status`, { status }),
  materials: (id) => api.get(`/schedules/${id}/materials`), // alokasi material batch + status stok GLOBAL
};

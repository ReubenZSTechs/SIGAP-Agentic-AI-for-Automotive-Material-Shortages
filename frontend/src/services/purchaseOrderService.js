import api from './api';

export const purchaseOrderService = {
  list: (params) => api.get('/purchase-orders', { params }), // status, supplier_id, planning_run_id
  get: (id) => api.get(`/purchase-orders/${id}`),
  setStatus: (id, status) => api.patch(`/purchase-orders/${id}/status`, { status }),
  // Manual PO (tanpa planning run) + approval satu tingkat
  createManual: (body) => api.post('/purchase-orders', body),
  update: (id, body) => api.patch(`/purchase-orders/${id}`, body), // DRAFT / REJECTED
  submit: (id) => api.post(`/purchase-orders/${id}/submit`),
  approve: (id, approved_by) => api.post(`/purchase-orders/${id}/approve`, { approved_by }),
  reject: (id, rejected_by, reason) => api.post(`/purchase-orders/${id}/reject`, { rejected_by, reason }),
  receive: (id, items) => api.post(`/purchase-orders/${id}/receipts`, { items }), // [{po_item_id, qty_received}]
};

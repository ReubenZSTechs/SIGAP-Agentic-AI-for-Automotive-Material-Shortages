import api from './api';

export const materialService = {
  list: (params) => api.get('/materials', { params }),
  get: (id) => api.get(`/materials/${id}`),
  create: (body) => api.post('/materials', body),
  update: (id, body) => api.patch(`/materials/${id}`, body),
  remove: (id) => api.delete(`/materials/${id}`),
  listSuppliers: (id) => api.get(`/materials/${id}/suppliers`),
  linkSupplier: (id, body) => api.post(`/materials/${id}/suppliers`, body),
  updateLink: (id, supplierId, body) => api.patch(`/materials/${id}/suppliers/${supplierId}`, body),
  unlinkSupplier: (id, supplierId) => api.delete(`/materials/${id}/suppliers/${supplierId}`),
};

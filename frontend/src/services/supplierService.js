import api from './api';

export const supplierService = {
  list: (params) => api.get('/suppliers', { params }),
  get: (id) => api.get(`/suppliers/${id}`),
  create: (body) => api.post('/suppliers', body),
  update: (id, body) => api.patch(`/suppliers/${id}`, body),
  remove: (id) => api.delete(`/suppliers/${id}`),
};

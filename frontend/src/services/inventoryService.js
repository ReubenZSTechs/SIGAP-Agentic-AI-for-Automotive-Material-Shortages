import api from './api';

export const inventoryService = {
  list: (params) => api.get('/inventory', { params }),
  update: (materialId, body) => api.put(`/inventory/${materialId}`, body), // {on_hand?, safety_stock?}
  movements: (params) => api.get('/stock-movements', { params }),
};

import api from './api';

export const bomService = {
  addItem: (body) => api.post('/bom/items', body), // {parent_id, child_id, qty_per_parent}
  updateItem: (id, body) => api.patch(`/bom/items/${id}`, body), // {qty_per_parent}
  removeItem: (id) => api.delete(`/bom/items/${id}`),
  // Sub-part ("Made") dibuat langsung dari BOM + dipasang ke induk (atomik)
  addSubPart: (body) => api.post('/bom/sub-parts', body), // {parent_id, sku, name, uom, qty_per_parent}
  updateSubPart: (materialId, body) => api.patch(`/bom/sub-parts/${materialId}`, body), // {name?, uom?, is_active?}
  tree: (productId) => api.get(`/bom/${productId}/tree`),
  explosion: (productId, qty = 1) => api.get(`/bom/${productId}/explosion`, { params: { qty } }),
};

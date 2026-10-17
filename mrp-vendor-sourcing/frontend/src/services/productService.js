import api from './api';

// Master Produk Final (barang jual) — endpoint /products
export const productService = {
  list: (params) => api.get('/products', { params }),
  get: (id) => api.get(`/products/${id}`),
  create: (body) => api.post('/products', body), // {sku, name, uom, selling_price, specification}
  update: (id, body) => api.patch(`/products/${id}`, body),
  remove: (id) => api.delete(`/products/${id}`),
};

import { Routes, Route } from 'react-router-dom';
import AppLayout from '../components/layout/AppLayout';
import DashboardPage from '../pages/DashboardPage';
import MaterialsPage from '../pages/MaterialsPage';
import ProductsPage from '../pages/ProductsPage';
import SuppliersPage from '../pages/SuppliersPage';
import InventoryPage from '../pages/InventoryPage';
import BomPage from '../pages/BomPage';
import MpsPage from '../pages/MpsPage';
import PlanningRunPage from '../pages/PlanningRunPage';
import PurchaseOrdersPage from '../pages/PurchaseOrdersPage';
import PurchaseOrderDetailPage from '../pages/PurchaseOrderDetailPage';
import ManualPoPage from '../pages/ManualPoPage';
import NotFoundPage from '../pages/NotFoundPage';

export default function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="materials" element={<MaterialsPage />} />
        <Route path="suppliers" element={<SuppliersPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="bom" element={<BomPage />} />
        <Route path="mps" element={<MpsPage />} />
        <Route path="planning/:runId" element={<PlanningRunPage />} />
        <Route path="purchase-orders" element={<PurchaseOrdersPage />} />
        <Route path="purchase-orders/new" element={<ManualPoPage />} />
        <Route path="purchase-orders/:id/edit" element={<ManualPoPage />} />
        <Route path="purchase-orders/:id" element={<PurchaseOrderDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

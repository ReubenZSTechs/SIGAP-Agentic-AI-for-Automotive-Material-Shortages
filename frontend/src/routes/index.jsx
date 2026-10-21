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
import SupplierHubPage from '../pages/SupplierHubPage';
import HubApprovals from '../pages/supplierHub/HubApprovals';
import HubConversations from '../pages/supplierHub/HubConversations';
import HubManagerChat from '../pages/supplierHub/HubManagerChat';
import HubMissions from '../pages/supplierHub/HubMissions';
import HubDocuments from '../pages/supplierHub/HubDocuments';
import HubSettings from '../pages/supplierHub/HubSettings';
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
        <Route path="supplier-hub" element={<SupplierHubPage />}>
          <Route index element={<HubApprovals />} />
          <Route path="conversations" element={<HubConversations />} />
          <Route path="conversations/:id" element={<HubConversations />} />
          <Route path="manager" element={<HubManagerChat />} />
          <Route path="missions" element={<HubMissions />} />
          <Route path="missions/:id" element={<HubMissions />} />
          <Route path="documents" element={<HubDocuments />} />
          <Route path="documents/:id" element={<HubDocuments />} />
          <Route path="settings" element={<HubSettings />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

from fastapi import APIRouter

from app.api.v1.endpoints import (materials, products, suppliers, inventory, bom, production_lines,
                                  schedules, planning, purchase_orders)

api_router = APIRouter()
api_router.include_router(materials.router,       prefix="/materials",       tags=["Master Material Beli"])
api_router.include_router(products.router,        prefix="/products",        tags=["Master Produk Final"])
api_router.include_router(suppliers.router,       prefix="/suppliers",       tags=["Master Supplier"])
api_router.include_router(inventory.router,       tags=["Inventory"])
api_router.include_router(bom.router,             prefix="/bom",             tags=["BOM"])
api_router.include_router(production_lines.router, prefix="/production-lines", tags=["MPS"])
api_router.include_router(schedules.router,       prefix="/schedules",       tags=["MPS"])
api_router.include_router(planning.router,        prefix="/planning",        tags=["Planning & Sourcing"])
api_router.include_router(purchase_orders.router, prefix="/purchase-orders", tags=["Purchase Order"])
# auth.py / users.py dibiarkan non-aktif: autentikasi di luar scope MVP.

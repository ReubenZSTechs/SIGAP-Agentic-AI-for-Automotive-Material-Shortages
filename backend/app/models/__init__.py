# Registrasi seluruh model ke Base.metadata
from app.models.enums import (  # noqa: F401
    ProcurementType, StockStatus, ScheduleStatus, PlanningRunStatus,
    POStatus, POSource, MovementType, SourcingStrategy, ItemCategory,
)
from app.models.material import Material  # noqa: F401
from app.models.supplier import Supplier  # noqa: F401
from app.models.material_supplier import MaterialSupplier  # noqa: F401
from app.models.bom import BOMItem  # noqa: F401
from app.models.production_line import ProductionLine  # noqa: F401
from app.models.schedule import Schedule  # noqa: F401
from app.models.inventory import Inventory, StockMovement  # noqa: F401
from app.models.planning import PlanningRun, PlanningLine  # noqa: F401
from app.models.purchase_order import PurchaseOrder, POItem  # noqa: F401
from app.chatbot import semantic_views  # noqa: F401,E402  (view chatbot ikut create_all/drop_all)

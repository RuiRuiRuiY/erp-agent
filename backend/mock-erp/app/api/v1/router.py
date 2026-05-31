from fastapi import APIRouter

from app.api.v1.budget import router as budget_router
from app.api.v1.department import router as department_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.pricing import router as pricing_router
from app.api.v1.product import router as product_router
from app.api.v1.supplier import router as supplier_router

api_router = APIRouter()
api_router.include_router(product_router)
api_router.include_router(supplier_router)
api_router.include_router(department_router)
api_router.include_router(budget_router)
api_router.include_router(inventory_router)
api_router.include_router(pricing_router)

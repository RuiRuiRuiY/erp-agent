"""SQLAdmin 管控台配置"""
from sqladmin import Admin, ModelView
from starlette.requests import Request

from app.core.database import engine
from app.model.admin import AdminUser
from app.model.budget import Budget
from app.model.department import Department
from app.model.inventory import Inventory
from app.model.product import Product
from app.model.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.model.supplier import Supplier
from app.model.supplier_pricelist import SupplierPricelist

# ── 角色权限定义 ──
# admin: 全部可见
# finance_manager: 全部可见（含强行审批相关页面）
# purchaser: 只能看基础数据，不能看管理员和采购单详情

ADMIN_ONLY = {"AdminUser"}
FINANCE_PLUS = {"AdminUser", "PurchaseOrder", "PurchaseOrderLine"}


def _check_role(request: Request, allowed_roles: set[str] | None = None) -> bool:
    """从 session/cookie 读取角色，判断是否有权限"""
    # 优先从 session 读取（SQLAdmin 登录后使用 session）
    role = request.session.get("role", "")
    # 也检查 cookie（API 登录使用 cookie）
    if not role:
        role = request.cookies.get("role", "")
    if not role:
        return False
    if allowed_roles is None:
        return True  # 不限角色，只要登录即可
    return role in allowed_roles


# ── 基础数据（所有已登录用户可见）──


class ProductAdmin(ModelView, model=Product):
    column_list = [Product.id, Product.sku, Product.name, Product.category, Product.is_active]
    column_searchable_list = [Product.name, Product.sku]
    can_create = True
    can_edit = True


class SupplierAdmin(ModelView, model=Supplier):
    column_list = [Supplier.id, Supplier.code, Supplier.name, Supplier.rating, Supplier.is_active]
    column_searchable_list = [Supplier.name, Supplier.code]
    can_create = True
    can_edit = True


class SupplierPricelistAdmin(ModelView, model=SupplierPricelist):
    column_list = [SupplierPricelist.supplier_id, SupplierPricelist.product_id,
                   SupplierPricelist.min_qty, SupplierPricelist.unit_price]
    can_create = True
    can_edit = True


class DepartmentAdmin(ModelView, model=Department):
    column_list = [Department.id, Department.code, Department.name]
    can_create = True
    can_edit = True


class BudgetAdmin(ModelView, model=Budget):
    column_list = [Budget.department_id, Budget.fiscal_year,
                   Budget.total_budget, Budget.used_budget, Budget.frozen_budget]
    can_create = True
    can_edit = True


class InventoryAdmin(ModelView, model=Inventory):
    column_list = [Inventory.product_id, Inventory.total_qty, Inventory.locked_qty]
    can_create = True
    can_edit = True


# ── 采购单（仅 admin + finance 可见）──


class PurchaseOrderAdmin(ModelView, model=PurchaseOrder):
    column_list = [PurchaseOrder.po_number, PurchaseOrder.supplier_id,
                   PurchaseOrder.department_id, PurchaseOrder.status,
                   PurchaseOrder.total_amount, PurchaseOrder.created_by_agent,
                   PurchaseOrder.is_override]
    column_searchable_list = [PurchaseOrder.po_number]
    can_create = False
    can_edit = False
    can_delete = False

    def is_accessible(self, request: Request) -> bool:
        return _check_role(request, {"admin", "finance_manager"})


class PurchaseOrderLineAdmin(ModelView, model=PurchaseOrderLine):
    column_list = [PurchaseOrderLine.po_id, PurchaseOrderLine.product_id,
                   PurchaseOrderLine.quantity, PurchaseOrderLine.unit_price]
    can_create = False
    can_edit = False
    can_delete = False

    def is_accessible(self, request: Request) -> bool:
        return _check_role(request, {"admin", "finance_manager"})


# ── 管理员账号（仅 admin 可见）──


class AdminUserAdmin(ModelView, model=AdminUser):
    column_list = [AdminUser.username, AdminUser.role, AdminUser.is_active]
    can_create = True
    can_edit = True

    def is_accessible(self, request: Request) -> bool:
        return _check_role(request, {"admin"})


def setup_admin(app):
    """将 SQLAdmin 注册到 FastAPI app"""
    from app.dashboard.auth import AdminAuth

    admin = Admin(
        app, engine,
        title="Mocek ERP 管控台",
        authentication_backend=AdminAuth(),
    )

    admin.add_view(ProductAdmin)
    admin.add_view(SupplierAdmin)
    admin.add_view(SupplierPricelistAdmin)
    admin.add_view(DepartmentAdmin)
    admin.add_view(BudgetAdmin)
    admin.add_view(InventoryAdmin)
    admin.add_view(PurchaseOrderAdmin)
    admin.add_view(PurchaseOrderLineAdmin)
    admin.add_view(AdminUserAdmin)

    return admin

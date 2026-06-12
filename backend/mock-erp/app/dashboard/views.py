"""SQLAdmin 管控台配置"""
from sqladmin import Admin, ModelView

from app.core.database import engine
from app.model.admin import AdminUser
from app.model.budget import Budget
from app.model.department import Department
from app.model.inventory import Inventory
from app.model.product import Product
from app.model.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.model.supplier import Supplier
from app.model.supplier_pricelist import SupplierPricelist


# ── 基础数据 ──


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


# ── 采购单 ──


class PurchaseOrderAdmin(ModelView, model=PurchaseOrder):
    column_list = [PurchaseOrder.po_number, PurchaseOrder.supplier_id,
                   PurchaseOrder.department_id, PurchaseOrder.status,
                   PurchaseOrder.total_amount, PurchaseOrder.created_by_agent,
                   PurchaseOrder.is_override]
    column_searchable_list = [PurchaseOrder.po_number]
    can_create = False  # 采购单由 Agent 创建，管控台只读
    can_edit = False
    can_delete = False


class PurchaseOrderLineAdmin(ModelView, model=PurchaseOrderLine):
    column_list = [PurchaseOrderLine.po_id, PurchaseOrderLine.product_id,
                   PurchaseOrderLine.quantity, PurchaseOrderLine.unit_price]
    can_create = False
    can_edit = False
    can_delete = False


# ── 管理员账号 ──


class AdminUserAdmin(ModelView, model=AdminUser):
    column_list = [AdminUser.username, AdminUser.role, AdminUser.is_active]
    can_create = True
    can_edit = True


def setup_admin(app):
    """将 SQLAdmin 注册到 FastAPI app"""
    admin = Admin(app, engine, title="ERP-Agent 管控台")

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

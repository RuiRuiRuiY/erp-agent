from sqlmodel import Session, select

from app.core.exceptions import BusinessException, ResourceNotFoundError
from app.model.inventory import Inventory


def get_inventory_by_product_id(
    session: Session, product_id: str,
) -> Inventory:
    stmt = select(Inventory).where(Inventory.product_id == product_id)
    inv = session.exec(stmt).first()
    if not inv:
        raise ResourceNotFoundError(
            resource="Inventory", resource_id=product_id,
        )
    return inv


def lock_stock(session: Session, product_id: str, qty: int) -> None:
    """原子锁定库存（锁定量增加），需在事务内调用。"""
    inv = get_inventory_by_product_id(session, product_id)
    available = inv.total_qty - inv.locked_qty
    if available < qty:
        raise BusinessException(
            error_code="INSUFFICIENT_STOCK",
            message=f"商品 {product_id} 库存不足",
            context={
                "product_id": product_id,
                "requested": qty,
                "available": available,
            },
            suggestion="建议减少数量、等待补货或寻找替代品",
        )
    inv.locked_qty += qty
    session.add(inv)


def unlock_stock(session: Session, product_id: str, qty: int) -> None:
    """原子释放库存锁定。"""
    inv = get_inventory_by_product_id(session, product_id)
    inv.locked_qty -= qty
    session.add(inv)


def consume_stock(session: Session, product_id: str, qty: int) -> None:
    """原子消耗库存（锁定 → 实际出库），扣减 total_qty 和 locked_qty。"""
    inv = get_inventory_by_product_id(session, product_id)
    inv.total_qty -= qty
    inv.locked_qty -= qty
    session.add(inv)


def reverse_consume_stock(session: Session, product_id: str, qty: int) -> None:
    """反向操作：恢复已消耗的库存。"""
    inv = get_inventory_by_product_id(session, product_id)
    inv.total_qty += qty
    session.add(inv)

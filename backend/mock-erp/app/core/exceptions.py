from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class BusinessException(Exception):  # noqa: N818
    def __init__(
        self,
        error_code: str,
        message: str,
        context: dict | None = None,
        suggestion: str | None = None,
        status_code: int = status.HTTP_409_CONFLICT,
    ):
        self.error_code = error_code
        self.message = message
        self.context = context or {}
        self.suggestion = suggestion
        self.status_code = status_code
        super().__init__(message)


class BudgetInsufficientError(BusinessException):
    def __init__(self, required: int, remaining: int, **kwargs):
        super().__init__(
            error_code="BUDGET_INSUFFICIENT",
            message="部门预算不足，无法完成操作",
            context={"required": required, "remaining": remaining, "deficit": required - remaining},
            suggestion="建议减少采购数量或申请追加预算",
            **kwargs,
        )


class InsufficientStockError(BusinessException):
    def __init__(self, product_id: str, requested: int, available: int, **kwargs):
        super().__init__(
            error_code="INSUFFICIENT_STOCK",
            message=f"商品 {product_id} 库存不足",
            context={"product_id": product_id, "requested": requested, "available": available},
            suggestion="建议减少数量、等待补货或寻找替代品",
            **kwargs,
        )


class InvalidStateTransitionError(BusinessException):
    def __init__(self, current: str, target: str, **kwargs):
        super().__init__(
            error_code="INVALID_STATE_TRANSITION",
            message=f"不允许从 {current} 跳转到 {target}",
            context={"current_status": current, "target_status": target},
            suggestion="请检查采购单当前状态并选择合法的流转路径",
            **kwargs,
        )


class ResourceNotFoundError(BusinessException):
    def __init__(self, resource: str, resource_id: str, **kwargs):
        super().__init__(
            error_code="RESOURCE_NOT_FOUND",
            message=f"{resource} {resource_id} 不存在",
            context={"resource": resource, "resource_id": resource_id},
            status_code=status.HTTP_404_NOT_FOUND,
            **kwargs,
        )


class PermissionDeniedError(BusinessException):
    def __init__(self, required_role: str, **kwargs):
        super().__init__(
            error_code="PERMISSION_DENIED",
            message=f"需要 {required_role} 权限才能执行此操作",
            context={"required_role": required_role},
            status_code=status.HTTP_403_FORBIDDEN,
            **kwargs,
        )


class PricingTierNotFoundError(BusinessException):
    def __init__(self, product_id: str, quantity: int, **kwargs):
        super().__init__(
            error_code="PRICING_TIER_NOT_FOUND",
            message=f"商品 {product_id} 在数量 {quantity} 下无匹配报价",
            context={"product_id": product_id, "quantity": quantity},
            suggestion="请尝试调整采购数量或更换商品",
            **kwargs,
        )


def _build_error_response(exc: BusinessException) -> JSONResponse:
    body = {
        "error_code": exc.error_code,
        "message": exc.message,
        "context": exc.context,
    }
    if exc.suggestion:
        body["agent_suggestion"] = exc.suggestion
    return JSONResponse(status_code=exc.status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessException)
    async def business_exception_handler(_request: Request, exc: BusinessException):
        return _build_error_response(exc)

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(_request: Request, exc: IntegrityError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error_code": "DB_INTEGRITY_ERROR",
                "message": "数据库约束冲突，操作被拒绝",
                "context": {"detail": str(exc.orig) if exc.orig else str(exc)},
                "agent_suggestion": "请检查数据完整性约束（如外键、唯一性、状态机校验）",
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, _exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "context": {},
                "agent_suggestion": "请联系系统管理员",
            },
        )

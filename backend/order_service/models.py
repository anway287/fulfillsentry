from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from enum import Enum
import uuid


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PICKING = "PICKING"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class Address(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    line1: str = Field(..., min_length=1, max_length=255)
    line2: Optional[str] = None
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=2, max_length=2)
    zip_code: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    country: str = Field(default="US", min_length=2, max_length=2)


class LineItem(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(..., gt=0, description="Must be greater than 0")


class CreateOrderRequest(BaseModel):
    merchant_id: str = Field(..., min_length=1, max_length=50)
    line_items: List[LineItem] = Field(..., min_length=1)
    shipping_address: Address
    idempotency_key: Optional[str] = Field(None, max_length=255)

    @field_validator("line_items")
    @classmethod
    def unique_skus(cls, v):
        skus = [item.sku for item in v]
        if len(skus) != len(set(skus)):
            raise ValueError("Duplicate SKUs in a single order are not allowed")
        return v


class OrderResponse(BaseModel):
    order_id: str
    merchant_id: str
    status: OrderStatus
    line_items: List[LineItem]
    shipping_address: Address
    idempotency_key: Optional[str] = None
    created_at: str


class UpdateOrderStatusRequest(BaseModel):
    status: OrderStatus


class FulfillOrderRequest(BaseModel):
    carrier: str = Field(..., min_length=1)
    tracking_number: str = Field(..., min_length=1)
    label_url: Optional[str] = None

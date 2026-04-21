from datetime import date
from typing import List, Optional
from pydantic import BaseModel, field_validator, model_validator


class Truck(BaseModel):
    id: str
    max_weight_lbs: int
    max_volume_cuft: int

    @field_validator("max_weight_lbs", "max_volume_cuft")
    @classmethod
    def must_be_positive(cls, v: int, info) -> int:
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return v


class Order(BaseModel):
    id: str
    payout_cents: int
    weight_lbs: int
    volume_cuft: int
    origin: str
    destination: str
    pickup_date: date
    delivery_date: date
    is_hazmat: bool

    @field_validator("payout_cents", "weight_lbs", "volume_cuft")
    @classmethod
    def must_be_positive(cls, v: int, info) -> int:
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return v

    @model_validator(mode="after")
    def pickup_before_delivery(self) -> "Order":
        if self.pickup_date > self.delivery_date:
            raise ValueError(
                f"Order {self.id}: pickup_date must be <= delivery_date"
            )
        return self


MAX_ORDERS = 22


class OptimizeRequest(BaseModel):
    truck: Truck
    orders: List[Order]

    @field_validator("orders")
    @classmethod
    def orders_not_empty(cls, v: List["Order"]) -> List["Order"]:
        if not v:
            raise ValueError("orders must not be empty")
        return v

    @model_validator(mode="after")
    def no_duplicate_order_ids(self) -> "OptimizeRequest":
        ids = [o.id for o in self.orders]
        seen, dupes = set(), set()
        for oid in ids:
            if oid in seen:
                dupes.add(oid)
            seen.add(oid)
        if dupes:
            raise ValueError(f"Duplicate order IDs: {sorted(dupes)}")
        return self


class OptimizeResponse(BaseModel):
    truck_id: str
    selected_order_ids: List[str]
    total_payout_cents: int
    total_weight_lbs: int
    total_volume_cuft: int
    utilization_weight_percent: float
    utilization_volume_percent: float
    pareto_alternatives: Optional[List[dict]] = None

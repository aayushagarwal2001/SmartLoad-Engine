from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.models import OptimizeRequest, OptimizeResponse, MAX_ORDERS
from app.optimizer import optimize, best_per_group

app = FastAPI(title="SmartLoad Optimization API", version="1.0.0")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/api/v1/load-optimizer/optimize", response_model=OptimizeResponse, response_model_exclude_none=True)
def optimize_load(request: OptimizeRequest, include_alternatives: bool = False):
    truck = request.truck
    orders = request.orders

    if len(orders) > MAX_ORDERS:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Too many orders: maximum is {MAX_ORDERS}"},
        )

    result = optimize(truck, orders)

    w_pct = round(result.total_weight_lbs / truck.max_weight_lbs * 100, 2)
    v_pct = round(result.total_volume_cuft / truck.max_volume_cuft * 100, 2)

    pareto_alts = None
    if include_alternatives and orders:
        selected_ids = {o.id for o in result.selected_orders}
        alts = []
        for alt in best_per_group(truck, orders):
            alt_ids = {o.id for o in alt.selected_orders}
            if alt_ids != selected_ids:
                alts.append({
                    "selected_order_ids": [o.id for o in alt.selected_orders],
                    "total_payout_cents": alt.total_payout_cents,
                    "total_weight_lbs": alt.total_weight_lbs,
                    "total_volume_cuft": alt.total_volume_cuft,
                })
        pareto_alts = alts if alts else None

    return OptimizeResponse(
        truck_id=truck.id,
        selected_order_ids=[o.id for o in result.selected_orders],
        total_payout_cents=result.total_payout_cents,
        total_weight_lbs=result.total_weight_lbs,
        total_volume_cuft=result.total_volume_cuft,
        utilization_weight_percent=w_pct,
        utilization_volume_percent=v_pct,
        pareto_alternatives=pareto_alts,
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    msg = str(exc)
    status = 413 if "Too many orders" in msg else 400
    return JSONResponse(status_code=status, content={"detail": msg})

# SmartLoad Optimization API

A stateless REST API that selects the optimal subset of shipping orders for a truck, maximizing carrier payout while respecting weight, volume, hazmat, and route constraints.

## Algorithm

**Bitmask DP** (O(2ⁿ), n ≤ 22):

1. **Pre-filter**: partition orders into compatibility groups by `(origin, destination, is_hazmat)`. Orders from different groups can never share a truck.
2. **Bitmask DP**: for each group, iterate all 2ⁿ subsets using incremental summation (each mask derived from its lowest-set-bit predecessor). Track the feasible subset with maximum `payout_cents`.
3. **Global best**: compare best results across all groups, return the highest payout.

**Bonus — Group alternatives**: pass `?include_alternatives=true` to receive `pareto_alternatives` — the best feasible load from each other compatibility group (different route or hazmat flag), useful for comparing trade-offs across groups.

**Money**: all values are `int` cents — never float.

## How to run

```bash
git clone <your-repo>
docker compose up --build
# Service available at http://localhost:8080
```

## Health check

```bash
curl http://localhost:8080/healthz
# {"status": "ok"}

curl http://localhost:8080/actuator/health
# {"status": "UP"}
```

## Example request

```bash
curl -X POST http://localhost:8080/api/v1/load-optimizer/optimize \
  -H "Content-Type: application/json" \
  -d @sample-request.json
```

Expected response:

```json
{
  "truck_id": "truck-123",
  "selected_order_ids": ["ord-001", "ord-002"],
  "total_payout_cents": 430000,
  "total_weight_lbs": 30000,
  "total_volume_cuft": 2100,
  "utilization_weight_percent": 68.18,
  "utilization_volume_percent": 70.0
}
```

### With group alternatives

```bash
curl -X POST "http://localhost:8080/api/v1/load-optimizer/optimize?include_alternatives=true" \
  -H "Content-Type: application/json" \
  -d @sample-request.json
```

`pareto_alternatives` will contain the best feasible load from each other compatibility group (e.g. a hazmat-only alternative). Omit the flag or pass `false` to suppress it (default).

## HTTP status codes

| Status | Condition |
|--------|-----------|
| 200 | Success |
| 400 | Invalid field values |
| 413 | More than 22 orders submitted |
| 422 | Missing required fields, constraint violations, empty orders, or no feasible combination |

## Run tests locally

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Constraints

- Stateless — no database
- Port 8080
- All money in integer cents
- Max 22 orders per request

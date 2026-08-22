#!/usr/bin/env bash
# Regression checks for the Swagger docs fix. Run against a live server.
BASE="${1:-http://127.0.0.1:8000}"
pass=0; fail=0

check() { # name expected actual
    if [ "$2" = "$3" ]; then
        echo "PASS  $1"
        pass=$((pass+1))
    else
        echo "FAIL  $1 (expected=$2 got=$3)"
        fail=$((fail+1))
    fi
}

echo "== Docs endpoints =="
check "GET /docs -> 200" 200 "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/docs")"
check "GET /docs has brand header" "yes" "$(curl -s "$BASE/docs" | grep -q 'forge-header' && echo yes || echo no)"
check "GET /docs loads generated schema" "yes" "$(curl -s "$BASE/docs" | grep -q "url: '/openapi.json'" && echo yes || echo no)"
check "GET /swagger/docs -> 308 to /docs" "$BASE/docs" "$(curl -s -o /dev/null -w '%{redirect_url}' "$BASE/swagger/docs")"
check "GET /swagger/openapi.json -> 308 to /openapi.json" "$BASE/openapi.json" "$(curl -s -o /dev/null -w '%{redirect_url}' "$BASE/swagger/openapi.json")"
check "GET /redoc -> 404 (disabled)" 404 "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/redoc")"

echo "== Generated schema =="
SCHEMA="$(curl -s "$BASE/openapi.json")"
check "schema title" "Forge AI API" "$(echo "$SCHEMA" | python -c 'import json,sys; print(json.load(sys.stdin)["info"]["title"])')"
check "StorageConfig schema exists" "yes" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print("yes" if "StorageConfig" in s["components"]["schemas"] else "no")')"
check "AppConfig has model example" "order-service" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print(s["components"]["schemas"]["AppConfig"]["examples"][0]["app_name"])')"
check "app_name is required" "yes" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print("yes" if "app_name" in s["components"]["schemas"]["AppConfig"].get("required",[]) else "no")')"
check "app_name has kebab pattern" "yes" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print("yes" if "pattern" in s["components"]["schemas"]["AppConfig"]["properties"]["app_name"] else "no")')"
check "env is an enum" "dev" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print(s["components"]["schemas"]["Environment"]["enum"][0])')"
check "S3 region example" "us-east-1" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print(s["components"]["schemas"]["S3Config"]["properties"]["region"]["examples"][0])')"
check "response model has app_name" "yes" "$(echo "$SCHEMA" | python -c 'import json,sys; s=json.load(sys.stdin); print("yes" if "app_name" in s["components"]["schemas"]["AppCreateResponse"]["properties"] else "no")')"

echo "== POST /app/create =="
RESP="$(curl -s -w '\n%{http_code}' -X POST "$BASE/app/create" -H 'Content-Type: application/json' -d "$FULL")"
check "full payload -> 200" 200 "$(echo "$RESP" | tail -1)"
check "full payload echoes app_name" "order-service" "$(echo "$RESP" | head -1 | python -c 'import json,sys; print(json.load(sys.stdin)["app_name"])')"
check "response has no service_type" "no" "$(echo "$RESP" | head -1 | python -c 'import json,sys; print("yes" if "service_type" in json.load(sys.stdin) else "no")')"

RESP="$(curl -s -w '\n%{http_code}' -X POST "$BASE/app/create" -H 'Content-Type: application/json' -d '{"app_name":"order-service"}')"
check "minimal payload -> 200" 200 "$(echo "$RESP" | tail -1)"
check "minimal payload echoes app_name" "order-service" "$(echo "$RESP" | head -1 | python -c 'import json,sys; print(json.load(sys.stdin)["app_name"])')"

check "empty payload -> 422" 422 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/app/create" -H 'Content-Type: application/json' -d '{}')"
check "bad app_name pattern -> 422" 422 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/app/create" -H 'Content-Type: application/json' -d '{"app_name":"Order Service!"}')"
check "bad env value -> 422" 422 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/app/create" -H 'Content-Type: application/json' -d '{"app_name":"order-service","envs":["qa"]}')"
check "capacity out of range -> 422" 422 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/app/create" -H 'Content-Type: application/json' -d '{"app_name":"order-service","services":[{"service_type":"fast-api","rel_database":{"name":"orders","capacity":99}}]}')"

echo
echo "RESULT: $pass passed, $fail failed"
exit $fail

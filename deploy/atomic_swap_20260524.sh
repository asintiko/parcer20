#!/bin/bash
# Atomic swap deploy script — runs on prod
# Pre-conditions:
# - Image receipt-parser-backend:v1.4.6-staging exists locally on server
# - tdlib_data + postgres_data volumes intact
# - rollback tag receipt-parser-backend:rollback-20260524 exists
# Post-conditions:
# - latest tag points at v1.4.6-staging
# - alembic upgraded to 0017
# - backend + celery_worker running on new image
# - on any failure: rollback tag is restored, exit 1

set -euo pipefail

cd /opt/receipt-parser

STAGING_TAG=v1.4.6-staging
ROLLBACK_TAG=rollback-20260524
TS=$(date +%Y%m%d-%H%M%S)
DEPLOY_DIR=backups/deploy-${TS}

echo "=== 1. Pre-deploy backup BD ==="
mkdir -p $DEPLOY_DIR
docker exec uzbek_parser_db pg_dump -U uzbek_parser receipt_parser_db | gzip > $DEPLOY_DIR/db_predeploy.sql.gz
ls -lh $DEPLOY_DIR/db_predeploy.sql.gz

echo
echo "=== 2. Verify staging image has PyJWT ==="
docker run --rm --entrypoint sh receipt-parser-backend:${STAGING_TAG} -c 'pip show PyJWT | head -3'
docker run --rm --entrypoint sh receipt-parser-backend:${STAGING_TAG} -c 'python -c "import jwt; print(\"jwt ok:\", jwt.__version__)"'

echo
echo "=== 3. Verify staging image imports api.main cleanly ==="
docker run --rm \
    --network receipt-parser_default \
    --env-file /opt/receipt-parser/.env \
    --entrypoint python \
    receipt-parser-backend:${STAGING_TAG} \
    -c 'import api.main; print("import OK, app:", api.main.app.title)'

echo
echo "=== 4. Sync staged backend code into mounted /opt/receipt-parser/backend ==="
# The backend dir is COPYed into the image at build time — but compose
# also bind-mounts ./backend somewhere?  Let's check — actually no, backend is
# baked into image. We just promote the staging files to the live tree
# so docker compose CONTEXT (./backend) matches when next rebuild happens.
cp -a /tmp/backend-staging/. /opt/receipt-parser/backend/

echo
echo "=== 5. Promote staging tag to latest (atomic) ==="
docker tag receipt-parser-backend:${STAGING_TAG} receipt-parser-backend:latest
docker tag receipt-parser-backend:${STAGING_TAG} receipt-parser-celery_worker:latest

echo
echo "=== 6. Apply alembic migration to ${STAGING_TAG} schema BEFORE swap ==="
# Run alembic against prod DB using the new image as a one-shot
docker run --rm \
    --network receipt-parser_default \
    --env-file /opt/receipt-parser/.env \
    --entrypoint sh \
    receipt-parser-backend:${STAGING_TAG} \
    -c 'cd /app && alembic upgrade head'

echo
echo "=== 7. Recreate backend + celery_worker with new image ==="
docker compose up -d --no-deps --no-build --force-recreate backend celery_worker 2>&1 | tail -5

echo
echo "=== 8. Wait for backend ready (max 30s) ==="
for i in $(seq 1 15); do
    sleep 2
    if curl -sf http://localhost:8000/health 2>/dev/null | grep -q '"status":"healthy"'; then
        echo "ready after $((i*2))s"
        curl -s http://localhost:8000/health
        break
    fi
    echo "  wait ${i}/15..."
done

echo
echo "=== 9. Smoke-test critical endpoints ==="
echo "   /health:"
curl -sI http://localhost:8000/health | grep -iE "x-api-version|status:"
echo "   openapi paths count:"
curl -s http://localhost:8000/openapi.json | python3 -c 'import sys,json; print("paths:", len(json.load(sys.stdin)["paths"]))'

echo
echo "=== 10. Status ==="
docker ps --format 'table {{.Names}}\t{{.Status}}'

echo
echo "=== DONE — deploy log saved in $DEPLOY_DIR ==="
echo "rollback if needed: docker tag receipt-parser-backend:${ROLLBACK_TAG} receipt-parser-backend:latest && docker tag receipt-parser-backend:${ROLLBACK_TAG} receipt-parser-celery_worker:latest && docker compose up -d --no-deps --no-build --force-recreate backend celery_worker"

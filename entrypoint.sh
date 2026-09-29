#!/bin/sh
set -e

echo "Waiting for the database..."
python - <<'CODE'
import os
import sys
import time

import psycopg

url = os.environ["DATABASE_URL"]
for attempt in range(30):
    try:
        psycopg.connect(url).close()
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("database never became ready", file=sys.stderr)
sys.exit(1)
CODE

python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "$SEED_DEMO" = "1" ]; then
    python manage.py seed_demo || true
fi

exec gunicorn config.asgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --access-logfile -

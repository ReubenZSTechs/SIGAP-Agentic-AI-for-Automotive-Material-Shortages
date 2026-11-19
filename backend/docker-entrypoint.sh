#!/bin/sh
set -eu

python - <<'PY'
import time
from sqlalchemy import create_engine, text
from app.config import settings

for attempt in range(60):
    try:
        with create_engine(settings.DATABASE_URL).connect() as c:
            c.execute(text("SELECT 1"))
        break
    except Exception as e:
        print(f"waiting for database ({attempt + 1}/60): {e.__class__.__name__}")
        time.sleep(1)
else:
    raise SystemExit("database not reachable")
PY

db_is_empty() {
  python - <<'PY'
import sys
from sqlalchemy import create_engine, inspect, text
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as c:
    has_data = inspect(c).has_table("materials") and c.execute(text("SELECT EXISTS (SELECT 1 FROM materials)")).scalar()
sys.exit(1 if has_data else 0)
PY
}

if [ "${SEED_DEMO:-false}" = "true" ] && db_is_empty; then
  python -m scripts.seed --demo-schedules
fi

exec "$@"

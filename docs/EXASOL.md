# Local Exasol setup

DEADLOCK uses PyExasol with TLS, explicit transactions, and the SQL in `sql/`. It never labels SQLite as Exasol.

## Recommended vendor installation

Use [Exasol Personal's official local deployment guide](https://exasol.github.io/exasol-personal/latest/local-deployment.html). Review and accept the vendor's license terms yourself before installation. Run its `info` command for connection information, and configure the four Exasol environment variables in `.env`.

The validation machine's native VM hit a kernel panic. The failed VM was stopped; a working database was started from the official ARM64 Nano image supplied in that same installation. This is a tested local fallback, not a claim that the vendor VM works on every Mac.

## Tested Docker fallback

Tested image: `exasol/nano:2026.2.0-nano.2`, ARM64, reporting database version `2026.2.0-dev.0`. Requires a running Docker engine and approximately 4 GiB of container memory. The vendor-provided image was loaded from its local install archive:

```sh
docker load -i "$HOME/.exasol/personal/deployments/deadlock/local/runtime/vm-shared/init/exasol-nano-db.tar.gz"
docker run --name deadlock-exasol --detach \
  --cpus 2 --memory 4g --shm-size 512m --pids-limit 4096 \
  --publish 127.0.0.1:9563:8563 \
  --mount type=volume,source=deadlock-exasol-data,target=/exa \
  exasol/nano:2026.2.0-nano.2 init params=maxConnectionsLicenseLimit=20
```

The archive path depends on the deployment name. If you already have an Exasol instance, use it instead. The data volume persists when the container stops. Stop/start only this container with `docker stop deadlock-exasol` / `docker start deadlock-exasol`.

Wait for `docker logs --tail 30 deadlock-exasol` to report that the database accepts connections. Copy its certificate through the local Docker connection, then calculate the SHA-256 certificate fingerprint:

```sh
mkdir -p .deadlock
docker cp deadlock-exasol:/exa/certificates/fullchain.pem .deadlock/exasol-cert.pem
uv run python - <<'PY'
import hashlib, ssl
from pathlib import Path
certificate = ssl.PEM_cert_to_DER_cert(Path('.deadlock/exasol-cert.pem').read_text())
print('127.0.0.1/' + hashlib.sha256(certificate).hexdigest() + ':9563')
PY
```

Set that result as `EXASOL_DSN`; the fingerprint goes **before** the port. Use the database credentials provided by the official local installer. Keep `.env` private (`chmod 600 .env`). The initial Nano SYS credential is for local setup; use a dedicated schema/user for a durable installation. The account needs permission to create/open the selected schema and create, select, insert, and update its tables.

```dotenv
DEADLOCK_DATABASE=exasol
EXASOL_DSN=127.0.0.1/VERIFIED_SHA256_FINGERPRINT:9563
EXASOL_USER=YOUR_DATABASE_USER
EXASOL_PASSWORD=YOUR_DATABASE_PASSWORD
EXASOL_SCHEMA=DEADLOCK
```

Restart DEADLOCK after changing engine configuration. Connections shows the actual engine and availability. The lab's SQL evidence dialog reports the executed SQL, snapshot, rows, and timing.

## Isolated validation

Each independent writer should have its own schema. In particular, avoid starting the test suite and evaluator against the same schema: Exasol may reject competing table transactions. The app uses one runner mutex and one database connection.

```sh
DEADLOCK_TEST_DATABASE=exasol EXASOL_SCHEMA=DEADLOCK_TEST uv run pytest -q
EXASOL_SCHEMA=DEADLOCK_EVAL PYTHONPATH=backend uv run python scripts/evaluate.py --live --trials 5
```

A lost connection disables recovery. The runner buffers at most 32 snapshots, marks any overflow as an evidence gap, and supports explicit reconnect. A run with an evidence gap cannot report verified recovery; start a new run after resolving the connection.

Sources: [Exasol Personal source](https://github.com/exasol/exasol-personal), [PyExasol connection API](https://exasol.github.io/pyexasol/master/api.html), [Exasol privileges](https://docs.exasol.com/db/latest/database_concepts/privileges.htm).

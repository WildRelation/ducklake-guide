# How to Use DuckDB in Python to Connect to a DuckLake (PostgreSQL + MinIO) Deployed on cbhcloud

## Architecture

DuckLake is not a service on its own — it is a **format** that defines how to organize a data lake. It requires two services to work:

```
DuckLake = PostgreSQL (catalog) + MinIO (parquet files)
```

**DuckDB** is the engine that understands the DuckLake format and connects both pieces together.

| Component | Role | Visibility |
|---|---|---|
| **PostgreSQL** (`ducklake-postgres2`) | Metadata catalog — stores table names, schemas, and transaction history | Private |
| **MinIO** (`ducklake-minio`) | Object storage — stores the actual `.parquet` data files | Public |
| **DuckDB** (local Python) | Query engine — reads the catalog and the files, returns results | — |

When you run `SELECT * FROM my_lake.main.some_table`, DuckDB:
1. Asks PostgreSQL — *where are the files for this table?*
2. Goes to MinIO — *downloads that `.parquet` file*
3. Returns the results to you

### What is a bucket?

A **bucket** is a root folder in MinIO. You cannot store files in MinIO without one. Think of it like this:

```
MinIO
  └── ducklake/            ← bucket
        └── table1.parquet
        └── table2.parquet
```

---

## Prerequisites

- Python 3.10+
- OpenSSH (pre-installed on Linux, macOS, and Windows 10/11)

---

## Step 1 — Open the SSH Tunnel to PostgreSQL

PostgreSQL is set to private, so it is not reachable directly from the internet. You need to forward its port to your local machine before running the script.

Open a terminal and leave this command running — **do not close it**:

```bash
ssh -L 5432:localhost:5432 ducklake-postgres2@deploy.cloud.cbh.kth.se -N
```

This makes your machine listen on `localhost:5432` and forward everything to PostgreSQL on cbhcloud. The same command works on Linux, macOS, and Windows PowerShell.

---

## Step 2 — Set Up the Python Environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**`requirements.txt`**

```
duckdb
minio
pandas
numpy
```

> The `ducklake` and `postgres` DuckDB extensions are **not pip packages** — they are installed automatically by the `INSTALL` commands inside the script.

---

## Step 3 — Create `main.py`

```python
import duckdb
from minio import Minio

# ── MinIO credentials (public on cbhcloud) ──────────────────────────────────
MINIO_ENDPOINT = "ducklake-minio.app.cloud.cbh.kth.se"
MINIO_USER     = "minioadmin"
MINIO_PASSWORD = "87654321"
BUCKET_NAME    = "ducklake"

# ── PostgreSQL credentials (private, reachable via SSH tunnel) ───────────────
PG_HOST     = "localhost"   # the tunnel forwards localhost:5432 → cbhcloud
PG_DB       = "ducklake"
PG_USER     = "duck"
PG_PASSWORD = "123456"
PG_PORT     = 5432


def ensure_bucket():
    """Creates the MinIO bucket if it does not exist."""
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASSWORD, secure=True)
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)
        print(f"Bucket '{BUCKET_NAME}' created.")


def connect():
    """Returns a DuckDB connection with the DuckLake catalog attached."""
    con = duckdb.connect()

    # Install extensions (only needed the first time — cached afterwards)
    con.execute("INSTALL ducklake;")
    con.execute("INSTALL postgres;")
    con.execute("LOAD ducklake;")
    con.execute("LOAD postgres;")

    # Tell DuckDB how to reach MinIO (S3-compatible storage)
    # URL_STYLE 'path' is required for MinIO — it does not support virtual-hosted style
    con.execute(f"""
    CREATE OR REPLACE SECRET minio_secret (
        TYPE s3,
        KEY_ID '{MINIO_USER}',
        SECRET '{MINIO_PASSWORD}',
        ENDPOINT '{MINIO_ENDPOINT}',
        URL_STYLE 'path',
        USE_SSL true
    );
    """)

    # Attach the DuckLake catalog:
    #   - "ducklake:postgres:..." tells DuckDB the catalog lives in PostgreSQL
    #   - DATA_PATH must match the path already registered in the catalog
    con.execute(f"""
    ATTACH 'ducklake:postgres:host={PG_HOST} dbname={PG_DB} user={PG_USER} password={PG_PASSWORD} port={PG_PORT}'
    AS my_lake (DATA_PATH 's3://{BUCKET_NAME}/');
    """)

    return con


def main():
    ensure_bucket()
    con = connect()
    print("Connected to DuckLake.\n")

    # List only user tables (exclude DuckLake internal metadata tables)
    tables = con.execute("""
        SELECT database, schema, name
        FROM (SHOW ALL TABLES)
        WHERE database = 'my_lake'
    """).fetchall()

    print("Tables in my_lake:")
    for db, schema, name in tables:
        print(f"  {db}.{schema}.{name}")

    # Example queries
    print("\n--- kunder ---")
    print(con.execute("SELECT * FROM my_lake.main.kunder LIMIT 5").fetchdf())

    print("\n--- produkter ---")
    print(con.execute("SELECT * FROM my_lake.main.produkter LIMIT 5").fetchdf())

    print("\n--- ordrar ---")
    print(con.execute("SELECT * FROM my_lake.main.ordrar LIMIT 5").fetchdf())


if __name__ == "__main__":
    main()
```

---

## Step 4 — Run the Script

With the SSH tunnel active (Step 1), open a second terminal:

```bash
python main.py
```

---

## Key Notes

**Why `localhost` as the PostgreSQL host?**
The SSH tunnel forwards `localhost:5432` to the real server on cbhcloud. If you close the terminal running the tunnel, the script cannot reach PostgreSQL.

**Why `URL_STYLE 'path'`?**
MinIO does not support virtual-hosted style URLs (`bucket.endpoint.com`). It requires path-style (`endpoint.com/bucket`).

**Why is `DATA_PATH` exactly `s3://ducklake/`?**
DuckLake stores the data path inside the PostgreSQL catalog when it is first initialized. If you provide a different path, DuckDB throws a mismatch error. The correct value is whatever is already registered in the catalog.

**What are the `__ducklake_metadata_*` tables?**
These are internal DuckLake tables used to manage the catalog (snapshots, columns, files). Do not modify them. Your actual data lives in the tables without that prefix.

**Does this involve Docker?**
Not on your side. The cbhcloud deployments (PostgreSQL and MinIO) run as Docker containers internally using the `postgres:16-alpine` and `minio/minio` images. You do not need Docker locally.

**Does this involve an API?**
No. DuckDB connects directly to PostgreSQL using the Postgres wire protocol and to MinIO using the S3 protocol. There is no HTTP server or REST API involved.

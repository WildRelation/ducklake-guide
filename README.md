# How to Use DuckDB in Python to Connect to a DuckLake (PostgreSQL + MinIO)

## How it works

DuckLake is not a service on its own — it is a **format** that defines how to organize a data lake. It requires two services to work:

```
DuckLake = PostgreSQL (catalog) + MinIO (parquet files)
```

**DuckDB** is the engine that understands the DuckLake format and connects both pieces together.

| Component | Role |
|---|---|
| **PostgreSQL** | Metadata catalog — stores table names, schemas, and transaction history |
| **MinIO** | Object storage — stores the actual `.parquet` data files |
| **DuckDB** (local Python) | Query engine — reads the catalog and the files, returns results |

When you run `SELECT * FROM my_lake.main.some_table`, DuckDB:
1. Asks PostgreSQL — *where are the files for this table?*
2. Goes to MinIO — *downloads that `.parquet` file*
3. Returns the results to you

### What is a bucket?

A **bucket** is a root folder in MinIO. You cannot store files in MinIO without one. Think of it like this:

```
MinIO
  └── your-bucket/         ← bucket
        └── table1.parquet
        └── table2.parquet
```

---

## Prerequisites

- Python 3.10+
- OpenSSH (pre-installed on Linux, macOS, and Windows 10/11)
- Your PostgreSQL and MinIO deployments up and running

---

## Step 1 — Check your deployment visibility

PostgreSQL handles metadata via the PostgreSQL wire protocol (port 5432). Most cloud platforms only expose HTTP/HTTPS publicly, not raw TCP ports. This means **PostgreSQL typically cannot be reached directly from the internet** even when set to public.

MinIO serves data over HTTP/HTTPS and can be set to public without issues.

**Recommended visibility settings:**

| Service | Visibility |
|---|---|
| PostgreSQL | Private — connect via SSH tunnel |
| MinIO | Public — connect directly via HTTPS |

---

## Step 2 — Open an SSH tunnel to PostgreSQL

Open a terminal and leave this command running — **do not close it**:

```bash
ssh -L 5432:localhost:5432 <your-postgres-deployment>@<your-ssh-host> -N
```

This forwards `localhost:5432` on your machine to the PostgreSQL server. The same command works on Linux, macOS, and Windows PowerShell.

> **Example (cbhcloud):**
> ```bash
> ssh -L 5432:localhost:5432 ducklake-postgres2@deploy.cloud.cbh.kth.se -N
> ```

---

## Step 3 — Set up the Python environment

**Linux / macOS:**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## Step 4 — Create `main.py`

Fill in the values for your deployment:

```python
import duckdb
from minio import Minio

# ── MinIO credentials ────────────────────────────────────────────────────────
MINIO_ENDPOINT = "<your-minio-host>"   # public hostname, no port if HTTPS
MINIO_USER     = "<your-minio-user>"
MINIO_PASSWORD = "<your-minio-password>"
BUCKET_NAME    = "<your-bucket-name>"

# ── PostgreSQL credentials ───────────────────────────────────────────────────
PG_HOST     = "localhost"   # always localhost — the SSH tunnel handles routing
PG_DB       = "<your-postgres-db>"
PG_USER     = "<your-postgres-user>"
PG_PASSWORD = "<your-postgres-password>"
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

    con.execute("INSTALL ducklake;")
    con.execute("INSTALL postgres;")
    con.execute("LOAD ducklake;")
    con.execute("LOAD postgres;")

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

    # DATA_PATH must match the path already registered in the catalog
    con.execute(f"""
    ATTACH 'ducklake:postgres:host={PG_HOST} dbname={PG_DB} user={PG_USER} password={PG_PASSWORD} port={PG_PORT}'
    AS my_lake (DATA_PATH 's3://{BUCKET_NAME}/');
    """)

    return con


def main():
    ensure_bucket()
    con = connect()
    print("Connected to DuckLake.\n")

    tables = con.execute("""
        SELECT database, schema, name
        FROM (SHOW ALL TABLES)
        WHERE database = 'my_lake'
    """).fetchall()

    print("Tables in my_lake:")
    if tables:
        for db, schema, name in tables:
            print(f"  {db}.{schema}.{name}")
    else:
        print("  (empty — no tables yet)")


if __name__ == "__main__":
    main()
```

> **Example (cbhcloud):**
> ```python
> MINIO_ENDPOINT = "ducklake-minio.app.cloud.cbh.kth.se"
> MINIO_USER     = "minioadmin"
> MINIO_PASSWORD = "87654321"
> BUCKET_NAME    = "ducklake"
>
> PG_HOST     = "localhost"
> PG_DB       = "ducklake"
> PG_USER     = "duck"
> PG_PASSWORD = "123456"
> PG_PORT     = 5432
> ```

---

## Step 5 — Run the script

With the SSH tunnel active (Step 2), open a second terminal:

```bash
python main.py
```

---

## CRUD operations

DuckLake supports full CRUD directly from Python — no API needed. Run the included example:

```bash
python crud.py
```

### Create

```python
con = connect()

con.execute("""
    CREATE TABLE IF NOT EXISTS my_lake.main.products (
        id    INT,
        name  VARCHAR,
        price DOUBLE,
        stock INT
    )
""")

con.execute("""
    INSERT INTO my_lake.main.products VALUES
        (1, 'Laptop',   9999.0, 15),
        (2, 'Mouse',     299.0, 50),
        (3, 'Keyboard', 1299.0, 30)
""")
```

### Read

```python
con.execute("SELECT * FROM my_lake.main.products").fetchdf()
```

### Update

```python
con.execute("""
    UPDATE my_lake.main.products
    SET price = 8999.0
    WHERE id = 1
""")
```

### Delete

```python
con.execute("""
    DELETE FROM my_lake.main.products
    WHERE id = 2
""")
```

> An API is only needed when you want to expose these operations to a web application or other users.

---

## Giving a team member access to the SSH tunnel (cbhcloud)

On cbhcloud, SSH tunnel access is restricted to the **owner** of the deployment. Sharing a deployment via "Share with team" gives the team member visibility in the dashboard but does not grant SSH tunnel access.

To give a team member SSH tunnel access:

### Step 1 — Team member creates a new SSH key

The new key must **not** already be registered on the team member's own cbhcloud profile — cbhcloud maps SSH keys to users, and a key registered on two profiles causes a conflict.

**Linux / macOS:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_shared
```

**Windows (PowerShell):**
```powershell
ssh-keygen -t ed25519 -f "C:\Users\<username>\.ssh\id_ed25519_shared"
```

### Step 2 — Team member sends you the public key

**Linux / macOS:**
```bash
cat ~/.ssh/id_ed25519_shared.pub
```

**Windows (PowerShell):**
```powershell
cat "C:\Users\<username>\.ssh\id_ed25519_shared.pub"
```

### Step 3 — Owner adds the key to their own cbhcloud profile

Go to your cbhcloud profile settings and add the team member's public key there.

### Step 4 — Team member opens the tunnel using the new key

**Linux / macOS:**
```bash
ssh -i ~/.ssh/id_ed25519_shared -L 5432:localhost:5432 <your-postgres-deployment>@deploy.cloud.cbh.kth.se -N
```

**Windows (PowerShell):**
```powershell
ssh -i "C:\Users\<username>\.ssh\id_ed25519_shared" -L 5432:localhost:5432 <your-postgres-deployment>@deploy.cloud.cbh.kth.se -N
```

The team member can then run the Python script as normal — `PG_HOST` stays `localhost`.

---

## Key Notes

**Why `localhost` as the PostgreSQL host?**
The SSH tunnel forwards `localhost:5432` to the real server. If you close the terminal running the tunnel, the script cannot reach PostgreSQL.

**Why `URL_STYLE 'path'`?**
MinIO does not support virtual-hosted style URLs (`bucket.endpoint.com`). It requires path-style (`endpoint.com/bucket`).

**Why must `DATA_PATH` match exactly?**
DuckLake stores the data path inside the PostgreSQL catalog when it is first initialized. If you provide a different path, DuckDB throws a mismatch error. Use whatever path is already registered in your catalog.

**What are the `__ducklake_metadata_*` tables?**
These are internal DuckLake tables used to manage the catalog (snapshots, columns, files). Do not modify them. Your actual data lives in the tables without that prefix.

**Does this involve Docker?**
Not on your side. If your PostgreSQL and MinIO are deployed on a cloud platform, they run as containers managed by that platform. You do not need Docker locally.

**Does this involve an API?**
No. DuckDB connects directly to PostgreSQL using the Postgres wire protocol and to MinIO using the S3 protocol. There is no HTTP server or REST API involved.

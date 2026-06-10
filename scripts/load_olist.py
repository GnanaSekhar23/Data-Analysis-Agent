import os
import sys
import yaml
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# 1. Load environment variables from .env
# ─────────────────────────────────────────────
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env file")
    sys.exit(1)

# ─────────────────────────────────────────────
# 2. Load dataset config
# ─────────────────────────────────────────────
config_path = os.path.join(os.path.dirname(__file__), "..", "dataset_config.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)

data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "olist")

print(f"\n{'='*50}")
print(f"  Loading: {config['name']}")
print(f"  Database: {config['database']}")
print(f"  Tables: {len(config['tables'])}")
print(f"{'='*50}\n")

# ─────────────────────────────────────────────
# 3. Connect to Cloud SQL
# ─────────────────────────────────────────────
print("Connecting to Cloud SQL...")
try:
    engine = create_engine(DATABASE_URL, echo=False)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT VERSION()"))
        version = result.fetchone()[0]
        print(f"Connected! MySQL version: {version}\n")
except Exception as e:
    print(f"ERROR connecting to database: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────
# 4. Helper — detect MySQL column types from pandas dtypes
# ─────────────────────────────────────────────
def get_mysql_type(series):
    """
    Looks at a pandas Series and returns the best MySQL type.
    - object dtype → TEXT (handles long strings, nulls safely)
    - int dtype    → BIGINT
    - float dtype  → DOUBLE
    - datetime     → DATETIME
    """
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    elif pd.api.types.is_float_dtype(series):
        return "DOUBLE"
    elif pd.api.types.is_datetime64_any_dtype(series):
        return "DATETIME"
    else:
        # For text columns, check max length to pick right type
        max_len = series.dropna().astype(str).str.len().max()
        if pd.isna(max_len) or max_len <= 255:
            return "VARCHAR(255)"
        else:
            return "TEXT"

# ─────────────────────────────────────────────
# 5. Helper — detect datetime columns automatically
# ─────────────────────────────────────────────
def detect_datetime_columns(df):
    """
    Finds columns whose name contains 'date', 'time', or 'timestamp'
    and tries to parse them as datetime. This matters for date filtering
    in SQL queries — storing as TEXT would break WHERE date > '2017-01-01'.
    """
    datetime_cols = []
    for col in df.columns:
        if any(keyword in col.lower() for keyword in ['date', 'time', 'timestamp']):
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                datetime_cols.append(col)
            except Exception:
                pass
    return df, datetime_cols

# ─────────────────────────────────────────────
# 6. Helper — create table from DataFrame
# ─────────────────────────────────────────────
def create_table(engine, table_name, df):
    """
    Builds a CREATE TABLE statement from the DataFrame's columns
    and types. Drops the table first if it already exists so the
    loader is safe to re-run (idempotent).
    """
    col_defs = []
    for col in df.columns:
        mysql_type = get_mysql_type(df[col])
        # Sanitize column name — replace spaces with underscores
        safe_col = col.strip().replace(" ", "_").replace("-", "_")
        col_defs.append(f"  `{safe_col}` {mysql_type}")

    col_sql = ",\n".join(col_defs)
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
{col_sql}
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    with engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
        conn.execute(text(create_sql))
        conn.commit()

# ─────────────────────────────────────────────
# 7. Helper — load CSV in batches
# ─────────────────────────────────────────────
def load_csv(engine, table_name, csv_path, batch_size=1000):
    """
    Loads a CSV into MySQL in batches of 1000 rows.
    Batching prevents memory issues on large files like
    geolocation (1M rows) and is much faster than row-by-row inserts.
    """
    print(f"  Reading {os.path.basename(csv_path)}...")
    df = pd.read_csv(csv_path, encoding='utf-8', low_memory=False)

    # Detect and parse datetime columns
    df, datetime_cols = detect_datetime_columns(df)
    if datetime_cols:
        print(f"  Detected datetime columns: {datetime_cols}")

    # Sanitize column names
    df.columns = [c.strip().replace(" ", "_").replace("-", "_") for c in df.columns]

    total_rows = len(df)
    print(f"  Total rows: {total_rows:,}")

    # Create the table
    create_table(engine, table_name, df)

    # Load in batches
    loaded = 0
    for i in range(0, total_rows, batch_size):
        batch = df.iloc[i:i+batch_size]
        batch.to_sql(
            table_name,
            engine,
            if_exists='append',    # append to existing table
            index=False,           # don't write pandas index as a column
            method='multi',        # faster multi-row INSERT
        )
        loaded += len(batch)
        pct = (loaded / total_rows) * 100
        # Progress bar
        bar = '█' * int(pct // 5) + '░' * (20 - int(pct // 5))
        print(f"\r  [{bar}] {pct:.1f}% ({loaded:,}/{total_rows:,} rows)", end='', flush=True)

    print()  # newline after progress bar
    return total_rows

# ─────────────────────────────────────────────
# 8. Main — loop through all tables in config
# ─────────────────────────────────────────────
summary = []

for table_config in config['tables']:
    table_name = table_config['name']
    csv_file   = table_config['file']
    csv_path   = os.path.join(data_dir, csv_file)

    print(f"\nLoading table: {table_name}")
    print(f"  Source: {csv_file}")

    if not os.path.exists(csv_path):
        print(f"  WARNING: File not found — skipping {csv_file}")
        summary.append((table_name, 0, "FILE NOT FOUND"))
        continue

    try:
        rows = load_csv(engine, table_name, csv_path)
        summary.append((table_name, rows, "OK"))
        print(f"  Done: {rows:,} rows loaded into `{table_name}`")
    except Exception as e:
        print(f"  ERROR loading {table_name}: {e}")
        summary.append((table_name, 0, str(e)))

# ─────────────────────────────────────────────
# 9. Add indexes for fast joins
# ─────────────────────────────────────────────
print(f"\n{'='*50}")
print("Adding indexes for fast joins...")

indexes = [
    ("orders",            "customer_id"),
    ("orders",            "order_status"),
    ("order_items",       "order_id"),
    ("order_items",       "product_id"),
    ("order_items",       "seller_id"),
    ("order_payments",    "order_id"),
    ("order_reviews",     "order_id"),
    ("products",          "product_category_name"),
    ("geolocation",       "geolocation_zip_code_prefix"),
]

with engine.connect() as conn:
    for table, col in indexes:
        try:
            idx_name = f"idx_{table}_{col}"
            conn.execute(text(f"CREATE INDEX `{idx_name}` ON `{table}` (`{col}`(50) )"))
            conn.commit()
            print(f"  Index added: {table}.{col}")
        except Exception as e:
            # Index might already exist — that's fine
            print(f"  Skipped index {table}.{col}: {e}")

# ─────────────────────────────────────────────
# 10. Print summary
# ─────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"  LOAD COMPLETE — {config['name']}")
print(f"{'='*50}")
print(f"  {'Table':<35} {'Rows':>10}  {'Status'}")
print(f"  {'-'*55}")
for table_name, rows, status in summary:
    print(f"  {table_name:<35} {rows:>10,}  {status}")

total = sum(r for _, r, s in summary if s == "OK")
print(f"  {'-'*55}")
print(f"  {'TOTAL':<35} {total:>10,}")
print(f"{'='*50}\n")
print("Next step: run the agent against this data!")
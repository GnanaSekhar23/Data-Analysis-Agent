import os
import json
import pymysql
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME     = os.getenv("DB_NAME")

def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        charset='utf8mb4',
        connect_timeout=10,
    )

# ─────────────────────────────────────────────────────
# Direct database tools — no MCP subprocess needed
# Simpler and more reliable than MCP for this use case
# ─────────────────────────────────────────────────────

def list_tables() -> list:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cur.fetchall()]
            result = []
            for table in tables:
                cur.execute(f"SELECT COUNT(*) as cnt FROM `{table}`")
                count = cur.fetchone()["cnt"]
                result.append({"table": table, "row_count": count})
            return result
    finally:
        conn.close()

def describe_table(table: str) -> dict:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DESCRIBE `{table}`")
            columns = cur.fetchall()
            cur.execute(f"SELECT * FROM `{table}` LIMIT 2")
            samples = cur.fetchall()
            return {
                "table": table,
                "columns": columns,
                "sample_rows": samples
            }
    finally:
        conn.close()

def run_query(sql: str) -> dict:
    # Safety check — only SELECT allowed
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        return {"error": "Only SELECT statements allowed"}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            truncated = len(rows) > 1000
            rows = list(rows[:1000])
            return {
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated
            }
    except pymysql.Error as e:
        return {"error": str(e), "sql": sql}
    finally:
        conn.close()

def run_write(sql: str, params=None) -> dict:
    allowed = ("INSERT", "UPDATE", "DELETE")
    if not any(sql.strip().upper().startswith(op) for op in allowed):
        return {"error": f"Only {', '.join(allowed)} allowed"}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            conn.commit()
            return {"success": True, "rows_affected": cur.rowcount}
    except pymysql.Error as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        conn.close()
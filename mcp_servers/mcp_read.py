import os
import sys
import json
import asyncio
from urllib.parse import quote_plus

import pymysql
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ─────────────────────────────────────────────────────
# 1. Load environment variables
#    We read DB credentials from .env so they never
#    get hardcoded into the source code
# ─────────────────────────────────────────────────────
load_dotenv()

DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME     = os.getenv("DB_NAME")

# ─────────────────────────────────────────────────────
# 2. Database connection helper
#    We create a fresh connection for every tool call
#    instead of a persistent connection — this is safer
#    for long-running servers (no stale connection issues)
# ─────────────────────────────────────────────────────
def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,  # returns rows as dicts not tuples
        charset='utf8mb4',
        connect_timeout=10,
    )

# ─────────────────────────────────────────────────────
# 3. Create the MCP server
#    The name "mysql-read" is what the agent sees
#    when it discovers available servers
# ─────────────────────────────────────────────────────
server = Server("mysql-read")

# ─────────────────────────────────────────────────────
# 4. Register available tools
#    This is like a menu — the agent reads this list
#    and decides which tool to call based on what it
#    needs to do. Each tool has:
#      - name: how the agent calls it
#      - description: what it does (agent reads this!)
#      - inputSchema: what parameters it accepts
# ─────────────────────────────────────────────────────
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="list_tables",
            description="""Lists all tables in the database with their row counts.
            Use this FIRST before writing any SQL to understand what data is available.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="describe_table",
            description="""Returns column names, data types, and sample values for a table.
            Use this before querying a table to understand its structure.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "The table name to describe"
                    }
                },
                "required": ["table"]
            }
        ),
        Tool(
            name="run_query",
            description="""Executes a SELECT SQL query and returns results as JSON.
            Only SELECT statements are allowed — no INSERT, UPDATE, DELETE.
            Always LIMIT results to avoid huge responses (use LIMIT 1000 max).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A valid MySQL SELECT statement"
                    }
                },
                "required": ["sql"]
            }
        ),
    ]

# ─────────────────────────────────────────────────────
# 5. Handle tool calls
#    When the agent calls a tool, this function runs.
#    It checks which tool was called, executes the
#    right logic, and returns a TextContent result
#    (always JSON string so the agent can parse it)
# ─────────────────────────────────────────────────────
@server.call_tool()
async def call_tool(name: str, arguments: dict):

    # ── Tool 1: list_tables ──────────────────────────
    if name == "list_tables":
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # Get all table names
                cur.execute("SHOW TABLES")
                tables = [list(row.values())[0] for row in cur.fetchall()]

                # Get row count for each table
                # This helps the agent know data volume before querying
                table_info = []
                for table in tables:
                    cur.execute(f"SELECT COUNT(*) as cnt FROM `{table}`")
                    count = cur.fetchone()["cnt"]
                    table_info.append({
                        "table": table,
                        "row_count": count
                    })

                return [TextContent(
                    type="text",
                    text=json.dumps(table_info, indent=2)
                )]
        finally:
            conn.close()

    # ── Tool 2: describe_table ───────────────────────
    elif name == "describe_table":
        table = arguments.get("table", "")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # DESCRIBE gives column name, type, nullable, key, default
                cur.execute(f"DESCRIBE `{table}`")
                columns = cur.fetchall()

                # Get 3 sample rows so the agent understands real data format
                # e.g. it learns that order_status = "delivered" not True/False
                cur.execute(f"SELECT * FROM `{table}` LIMIT 3")
                samples = cur.fetchall()

                result = {
                    "table": table,
                    "columns": columns,
                    "sample_rows": samples
                }

                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str)
                    # default=str handles datetime objects that aren't JSON serializable
                )]
        finally:
            conn.close()

    # ── Tool 3: run_query ────────────────────────────
    elif name == "run_query":
        sql = arguments.get("sql", "").strip()

        # Safety check — only allow SELECT statements
        # This prevents the read server from ever modifying data
        sql_upper = sql.upper().lstrip()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Only SELECT and WITH (CTE) statements allowed on this server. Use the write server for modifications."
                })
            )]

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

                # Cap at 1000 rows to avoid massive responses
                # The agent should use GROUP BY / aggregations for large data
                truncated = len(rows) > 1000
                rows = rows[:1000]

                result = {
                    "rows": rows,
                    "row_count": len(rows),
                    "truncated": truncated,
                    "message": "Results truncated to 1000 rows. Use aggregations for full dataset analysis." if truncated else None
                }

                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str)
                )]

        except pymysql.Error as e:
            # Return the MySQL error to the agent so it can
            # fix its SQL and retry — this powers the retry loop
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": str(e),
                    "sql": sql
                })
            )]
        finally:
            conn.close()

    else:
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"})
        )]

# ─────────────────────────────────────────────────────
# 6. Run the server
#    stdio_server means the agent communicates with
#    this server via stdin/stdout — standard MCP pattern
# ─────────────────────────────────────────────────────
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
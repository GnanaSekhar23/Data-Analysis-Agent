import os
import json
import asyncio
import pymysql
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

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

server = Server("mysql-write")

# ─────────────────────────────────────────────────────
# Allowed operations — whitelist approach
# The agent can ONLY call these specific operations.
# This prevents the agent from doing dangerous things
# like DROP TABLE or TRUNCATE accidentally
# ─────────────────────────────────────────────────────
ALLOWED_STATEMENTS = ("INSERT", "UPDATE", "DELETE")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="run_write",
            description="""Executes INSERT, UPDATE, or DELETE statements.
            Use only when the user explicitly asks to modify data.
            Always confirm the operation with the user before running DELETE.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A valid MySQL INSERT, UPDATE, or DELETE statement"
                    },
                    "params": {
                        "type": "array",
                        "description": "Optional parameterized values to safely bind into the SQL",
                        "items": {"type": "string"},
                        "default": []
                    }
                },
                "required": ["sql"]
            }
        ),
        Tool(
            name="run_transaction",
            description="""Executes multiple SQL statements as a single atomic transaction.
            If any statement fails, ALL are rolled back — nothing is partially saved.
            Use for operations that must succeed or fail together.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "statements": {
                        "type": "array",
                        "description": "List of SQL statements to run in one transaction",
                        "items": {"type": "string"}
                    }
                },
                "required": ["statements"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):

    if name == "run_write":
        sql = arguments.get("sql", "").strip()
        params = arguments.get("params", [])

        # Validate it's an allowed statement type
        sql_upper = sql.upper().lstrip()
        if not any(sql_upper.startswith(op) for op in ALLOWED_STATEMENTS):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Only {', '.join(ALLOWED_STATEMENTS)} allowed. Got: {sql[:50]}"
                })
            )]

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                conn.commit()
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "rows_affected": cur.rowcount,
                        "message": f"{cur.rowcount} row(s) affected"
                    })
                )]
        except pymysql.Error as e:
            conn.rollback()
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e), "sql": sql})
            )]
        finally:
            conn.close()

    elif name == "run_transaction":
        statements = arguments.get("statements", [])

        # Validate all statements before running any
        for sql in statements:
            sql_upper = sql.strip().upper()
            if not any(sql_upper.startswith(op) for op in ALLOWED_STATEMENTS):
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"All statements must be INSERT/UPDATE/DELETE. Got: {sql[:50]}"
                    })
                )]

        conn = get_connection()
        try:
            results = []
            with conn.cursor() as cur:
                for sql in statements:
                    cur.execute(sql)
                    results.append({
                        "sql": sql[:80],
                        "rows_affected": cur.rowcount
                    })
            conn.commit()  # commit ALL at once — atomic
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "statements_executed": len(statements),
                    "results": results
                })
            )]
        except pymysql.Error as e:
            conn.rollback()  # roll back ALL on any error
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e), "rolled_back": True})
            )]
        finally:
            conn.close()

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
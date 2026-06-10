import os
import json
import yaml
import base64
import io
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv
import google.auth
import google.auth.transport.requests
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from .state import AgentState
from .tools import list_tables, describe_table, run_query

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")

def get_llm():
    credentials, _ = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return ChatOpenAI(
        model="xai/grok-4.1-fast-reasoning",
        openai_api_base=f"https://aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/endpoints/openapi",
        openai_api_key=credentials.token,
        temperature=0,
        max_tokens=2048,
    )

CONFIG_PATH = Path(__file__).parent.parent / "dataset_config.yaml"
with open(CONFIG_PATH) as f:
    DATASET_CONFIG = yaml.safe_load(f)

sns.set_theme(style="whitegrid", palette="muted")

# ─────────────────────────────────────────────────────
# Node 1 — inspect_schema
# ─────────────────────────────────────────────────────
async def inspect_schema(state: AgentState) -> dict:
    print("[node] inspect_schema")
    schema = {}

    tables_result = list_tables()
    tables = [t["table"] for t in tables_result if t["table"] != "geolocation"]

    for table in tables:
        desc = describe_table(table)
        schema[table] = {
            "columns": desc.get("columns", []),
            "sample_rows": [],
        }

    return {
        "schema": schema,
        "hints": DATASET_CONFIG.get("hints", []),
        "error": "",
    }

# ─────────────────────────────────────────────────────
# Node 2 — generate_sql
# ─────────────────────────────────────────────────────
async def generate_sql(state: AgentState) -> dict:
    print("[node] generate_sql")
    llm = get_llm()

    schema_lines = []
    for table, info in state["schema"].items():
        cols = [c['Field'] for c in info["columns"]]
        schema_lines.append(f"`{table}`: {', '.join(cols)}")
    schema_str = "\n".join(schema_lines)
    hints_str  = "\n".join(f"- {h}" for h in state.get("hints", [])[:5])
    relations  = "\n".join(f"- {r}" for r in DATASET_CONFIG.get("relationships", [])[:5])

    system_prompt = f"""You are a MySQL expert. Return ONLY valid MySQL SQL — no markdown, no explanation, no backticks.

SCHEMA:
{schema_str}

RELATIONSHIPS:
{relations}

HINTS:
{hints_str}

Rules:
1. MySQL 8.0 syntax only
2. Use aliases (o for orders, oi for order_items, p for products, r for order_reviews, s for sellers)
3. NEVER use reserved words as aliases: or, and, in, by, as, on, is, to
4. Add LIMIT 100 unless aggregating
5. Return ONLY the SQL query"""

    prev_error = state.get("error", "")
    prev_sql   = state.get("sql", "")

    if prev_error and prev_sql:
        user_msg = f"""Question: {state['question']}

Previous SQL that failed:
{prev_sql}

MySQL Error:
{prev_error}

Fix the SQL and return only the corrected query."""
    else:
        user_msg = f"Question: {state['question']}"

    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_msg),
    ])

    sql = response.content.strip()
    sql = sql.replace("```sql", "").replace("```mysql", "").replace("```", "").strip()

    return {"sql": sql, "error": ""}

# ─────────────────────────────────────────────────────
# Node 3 — run_query
# ─────────────────────────────────────────────────────
async def run_query_node(state: AgentState) -> dict:
    print(f"[node] run_query — SQL: {state['sql'][:80]}...")

    result = run_query(state["sql"])

    if "error" in result:
        print(f"[node] run_query ERROR: {result['error']}")
        return {
            "error": result["error"],
            "retry_count": state.get("retry_count", 0) + 1,
            "raw_data": [],
        }

    return {
        "raw_data": result.get("rows", []),
        "error": "",
    }

# ─────────────────────────────────────────────────────
# Node 4 — analyze
# ─────────────────────────────────────────────────────
async def analyze(state: AgentState) -> dict:
    print("[node] analyze")
    llm = get_llm()

    rows     = state.get("raw_data", [])
    question = state["question"]

    if not rows:
        return {
            "analysis": "No data was returned for this query. Try rephrasing your question.",
            "json_output": {}
        }

    data_preview = json.dumps(rows[:50], indent=2, default=str)
    total_rows   = len(rows)

    response = await llm.ainvoke([
        SystemMessage(content=f"""You are a data analyst for {DATASET_CONFIG['name']}.
Analyze the query results and answer the user's question clearly.

Structure your response as:
1. Direct answer (1-2 sentences)
2. Key findings (bullet points with real numbers)
3. Trends or patterns
4. Anomalies or interesting observations
5. One actionable business recommendation"""),
        HumanMessage(content=f"""Question: {question}
Total rows: {total_rows}
Data: {data_preview}"""),
    ])

    json_output = {
        "question": question,
        "sql": state["sql"],
        "row_count": total_rows,
        "data": rows[:100],
        "analysis": response.content,
    }

    return {
        "analysis": response.content,
        "json_output": json_output,
    }

# ─────────────────────────────────────────────────────
# Node 5 — visualize
# ─────────────────────────────────────────────────────
async def visualize(state: AgentState) -> dict:
    print("[node] visualize")

    rows = state.get("raw_data", [])
    print(f"[visualize] rows count: {len(rows)}")

    if not rows or len(rows) < 2:
        print("[visualize] not enough rows — skipping chart")
        return {"chart_base64": "", "chart_type": "none"}

    try:
        df = pd.DataFrame(rows)
        print(f"[visualize] dataframe shape: {df.shape}")
        print(f"[visualize] columns: {df.columns.tolist()}")
        cols = df.columns.tolist()

        # Convert numeric-looking string columns to numbers
        for col in cols:
            try:
                df[col] = pd.to_numeric(df[col], errors='raise')
            except (ValueError, TypeError):
                pass

        # Detect column types after conversion
        date_cols = [c for c in cols if any(k in c.lower() for k in ['date','time','month','year','week'])]
        num_cols  = df.select_dtypes(include='number').columns.tolist()
        cat_cols  = [c for c in cols if c not in num_cols]

        print(f"[visualize] num_cols: {num_cols}, cat_cols: {cat_cols}")

        # Need at least one numeric column to chart
        if not num_cols:
            print("[visualize] no numeric columns — skipping chart")
            return {"chart_base64": "", "chart_type": "none"}

        # Pick x (category/date) and y (numeric) smartly
        x = date_cols[0] if date_cols else (cat_cols[0] if cat_cols else cols[0])
        y = num_cols[0]  # always first numeric column

        print(f"[visualize] x={x}, y={y}, chart_type detection...")

        # Detect chart type from question keywords
        question_lower = state["question"].lower()
        if any(w in question_lower for w in ["trend","monthly","weekly","over time","by month","by year","daily"]):
            chart_type = "line"
        elif any(w in question_lower for w in ["distribution","spread","histogram"]):
            chart_type = "histogram"
        elif any(w in question_lower for w in ["relationship","correlation","vs","versus"]):
            chart_type = "scatter"
        elif date_cols:
            chart_type = "line"
        elif cat_cols and len(df) <= 8:
            chart_type = "pie"
        else:
            chart_type = "bar"

        print(f"[visualize] chart_type={chart_type}")

        fig, ax = plt.subplots(figsize=(10, 5))

        if chart_type == "line":
            try:
                df[x] = pd.to_datetime(df[x], errors='coerce')
                if df[x].isna().all():
                    raise ValueError("not datetime")
                df = df.sort_values(x)
                ax.plot(df[x], df[y], marker='o', linewidth=2)
                ax.fill_between(df[x], df[y], alpha=0.1)
            except Exception:
                df_sorted = df.sort_values(y, ascending=False) if y in df.columns else df
                ax.plot(range(len(df_sorted)), df_sorted[y], marker='o', linewidth=2)
                ax.set_xticks(range(len(df_sorted)))
                ax.set_xticklabels(df_sorted[x].astype(str), rotation=45, ha='right')
            plt.xticks(rotation=45)

        elif chart_type == "bar":
            # Use nlargest only on numeric y column
            if len(df) > 15:
                df_plot = df.nlargest(15, y)
            else:
                df_plot = df.sort_values(y, ascending=False)
            bars = ax.bar(df_plot[x].astype(str), df_plot[y])
            ax.bar_label(bars, fmt='%.0f', padding=3, fontsize=9)
            plt.xticks(rotation=45, ha='right')

        elif chart_type == "pie":
            df_plot = df.nlargest(8, y) if len(df) > 8 else df
            ax.pie(df_plot[y], labels=df_plot[x].astype(str), autopct='%1.1f%%', startangle=90)

        elif chart_type == "histogram":
            ax.hist(df[y].dropna(), bins=20, edgecolor='white')
            ax.set_xlabel(y)
            ax.set_ylabel("Frequency")

        elif chart_type == "scatter":
            ax.scatter(df[x], df[y], alpha=0.6)
            ax.set_xlabel(x)
            ax.set_ylabel(y)

        ax.set_title(state["question"][:60], pad=15)
        if chart_type not in ("pie", "histogram"):
            ax.set_xlabel(x)
            ax.set_ylabel(y)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        print(f"[visualize] chart generated successfully — {len(img_base64)} bytes")
        return {"chart_base64": img_base64, "chart_type": chart_type}

    except Exception as e:
        import traceback
        print(f"[node] visualize error: {e}")
        print(traceback.format_exc())
        return {"chart_base64": "", "chart_type": "none"}
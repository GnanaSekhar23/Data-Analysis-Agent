import os
import json
import asyncio
import base64
import io
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # non-interactive backend — no GUI window needed
import matplotlib.pyplot as plt
import seaborn as sns
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("chart-generator")

# ─────────────────────────────────────────────────────
# Chart style — clean, professional look
# ─────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams.update({
    "figure.figsize": (10, 5),
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
})

def df_from_rows(rows: list) -> pd.DataFrame:
    """Convert the JSON rows from run_query into a DataFrame."""
    return pd.DataFrame(rows)

def fig_to_base64(fig) -> str:
    """
    Convert a matplotlib figure to a base64 PNG string.
    The React frontend receives this string and renders it
    as <img src="data:image/png;base64,..." />
    """
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="generate_chart",
            description="""Generates a chart from query result rows and returns a base64 PNG.
            Automatically picks the best chart type based on data shape,
            or use chart_type to specify: line, bar, histogram, scatter, pie.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "description": "The rows returned from run_query",
                        "items": {"type": "object"}
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title — usually the user's question"
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": ["auto", "line", "bar", "histogram", "scatter", "pie"],
                        "default": "auto",
                        "description": "Chart type. Use auto to let the server decide."
                    },
                    "x_col": {
                        "type": "string",
                        "description": "Column to use for X axis (optional for auto)"
                    },
                    "y_col": {
                        "type": "string",
                        "description": "Column to use for Y axis (optional for auto)"
                    }
                },
                "required": ["rows", "title"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name != "generate_chart":
        return [TextContent(type="text", text=json.dumps({"error": "Unknown tool"}))]

    rows       = arguments.get("rows", [])
    title      = arguments.get("title", "Analysis Result")
    chart_type = arguments.get("chart_type", "auto")
    x_col      = arguments.get("x_col")
    y_col      = arguments.get("y_col")

    if not rows:
        return [TextContent(type="text", text=json.dumps({"error": "No data to chart"}))]

    try:
        df = df_from_rows(rows)
        cols = df.columns.tolist()

        # ── Auto-detect columns ──────────────────────
        # Find date/time column for X axis
        
        cols = df.columns.tolist()

        # Find date/time column
        date_cols = [c for c in cols if any(
            k in c.lower() for k in ['date', 'time', 'month', 'year', 'week', 'period', 'day']
        )]

        # Find numeric columns
        num_cols = df.select_dtypes(include='number').columns.tolist()

        # Find text/category columns
        cat_cols = [c for c in cols if c not in num_cols]

        # Use provided cols or auto-detect
        x = x_col or (date_cols[0] if date_cols else (cat_cols[0] if cat_cols else cols[0]))
        y = y_col or (num_cols[0] if num_cols else cols[1] if len(cols) > 1 else cols[0])

        # ── Auto-detect chart type ───────────────────
        if chart_type == "auto":
            if date_cols:
                chart_type = "line"   # any time-related column → line
            elif cat_cols and num_cols and len(df) <= 8:
                chart_type = "pie"
            elif cat_cols and num_cols:
                chart_type = "bar"
            elif len(num_cols) >= 2:
                chart_type = "scatter"
            else:
                chart_type = "histogram"  # one number → distribution

        # ── Draw the chart ───────────────────────────
        fig, ax = plt.subplots()

        if chart_type == "line":
    # Try parsing as datetime, fall back to string labels
            try:
                df[x] = pd.to_datetime(df[x], errors='coerce')
                if df[x].isna().all():
                    raise ValueError("not datetime")
                df = df.sort_values(x)
                ax.plot(df[x], df[y], marker='o', linewidth=2, markersize=5)
                ax.fill_between(df[x], df[y], alpha=0.1)
            except:
                # String labels like "2017-01", "January" etc
                ax.plot(range(len(df)), df[y], marker='o', linewidth=2, markersize=5)
                ax.set_xticks(range(len(df)))
                ax.set_xticklabels(df[x].astype(str), rotation=45, ha='right')
                ax.fill_between(range(len(df)), df[y], alpha=0.1)
            plt.xticks(rotation=45)

        elif chart_type == "bar":
            df_plot = df.nlargest(15, y) if len(df) > 15 else df
            bars = ax.bar(df_plot[x].astype(str), df_plot[y], color=sns.color_palette("muted"))
            ax.bar_label(bars, fmt='%.0f', padding=3, fontsize=9)
            plt.xticks(rotation=45, ha='right')

        elif chart_type == "histogram":
            ax.hist(df[y].dropna(), bins=20, edgecolor='white', linewidth=0.5)
            ax.set_xlabel(y)
            ax.set_ylabel("Frequency")

        elif chart_type == "scatter":
            ax.scatter(df[x], df[y], alpha=0.6, s=30)
            ax.set_xlabel(x)
            ax.set_ylabel(y)

        elif chart_type == "pie":
            df_plot = df.nlargest(8, y)  # max 8 slices for readability
            ax.pie(
                df_plot[y],
                labels=df_plot[x].astype(str),
                autopct='%1.1f%%',
                startangle=90
            )

        ax.set_title(title, pad=15)
        if chart_type not in ("pie", "histogram", "scatter"):
            ax.set_xlabel(x)
            ax.set_ylabel(y)

        plt.tight_layout()
        img_base64 = fig_to_base64(fig)

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "chart_type": chart_type,
                "image_base64": img_base64,
                "x_col": x,
                "y_col": y,
                "data_points": len(df)
            })
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)})
        )]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
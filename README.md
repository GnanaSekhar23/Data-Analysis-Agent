# Data Analysis Agent

A natural language data analysis agent built with **LangGraph**, **MCP**, **FastAPI**, and **React**. Ask questions in plain English and get SQL queries, data analysis, and charts automatically.

![Data Analysis Agent](https://img.shields.io/badge/LangGraph-Agent-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green) ![React](https://img.shields.io/badge/React-Frontend-blue) ![GCP](https://img.shields.io/badge/GCP-Cloud%20SQL-orange)

---

## Demo

Ask questions like:
- *"What are the top 5 product categories by total revenue?"*
- *"Show me monthly order trends for 2017"*
- *"Which sellers have the highest average review score?"*
- *"What percentage of orders were delivered on time?"*
- *"Which payment methods are most popular?"*

The agent automatically:
1. Inspects the database schema
2. Writes the correct SQL query
3. Executes it against 1.55M rows of real data
4. Analyzes the results with AI
5. Generates a chart
6. Streams everything to the UI in real time

---

## Architecture

```
React Frontend (Vite + Tailwind)
        ↕ SSE Streaming
FastAPI Backend
        ↕
LangGraph Agent
    ├── inspect_schema  → reads DB structure
    ├── generate_sql    → Grok AI writes SQL
    ├── run_query       → executes against MySQL
    ├── analyze         → Grok AI analyzes results
    └── visualize       → generates charts
        ↕
GCP Cloud SQL (MySQL 8.4)
1.55M rows · 9 tables · Olist Brazilian E-Commerce
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | React + Vite + Tailwind | Chat UI, chart display, data table |
| Backend | FastAPI + SSE | REST API, real-time streaming |
| Agent | LangGraph | Workflow orchestration, retry logic |
| LLM | Grok 4.1 Fast via Vertex AI | SQL generation, data analysis |
| Database | GCP Cloud SQL (MySQL) | Production database |
| Protocol | MCP (Model Context Protocol) | Standardized tool interface |

---

## Project Structure

```
data-analysis-agent/
├── agent/
│   ├── __init__.py
│   ├── state.py          # LangGraph shared state
│   ├── nodes.py          # Agent nodes (inspect, generate, run, analyze, visualize)
│   ├── graph.py          # LangGraph graph wiring + retry logic
│   └── tools.py          # Direct DB tools (list_tables, run_query etc.)
├── mcp_servers/
│   ├── mcp_read.py       # Read MCP server (SELECT + schema)
│   ├── mcp_write.py      # Write MCP server (INSERT/UPDATE/DELETE)
│   └── mcp_chart.py      # Chart generation MCP server
├── frontend/
│   ├── src/
│   │   ├── App.jsx       # Main React component
│   │   ├── main.jsx      # React entry point
│   │   └── index.css     # Tailwind styles
│   ├── vite.config.js    # Vite + proxy config
│   └── package.json
├── scripts/
│   └── load_olist.py     # Data loader script
├── main.py               # FastAPI backend
├── dataset_config.yaml   # Dataset configuration (customizable)
├── test_agent.py         # Agent test script
└── .env                  # Environment variables (not committed)
```

---

## Dataset

Uses the [Olist Brazilian E-Commerce Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) from Kaggle.

| Table | Rows | Description |
|-------|------|-------------|
| orders | 99,441 | Main orders table |
| customers | 99,441 | Customer details |
| order_items | 112,650 | Items per order |
| order_payments | 103,886 | Payment details |
| order_reviews | 99,224 | Customer reviews |
| products | 32,951 | Product catalog |
| sellers | 3,095 | Seller details |
| product_category_translation | 71 | Category name translations |
| geolocation | 1,000,163 | ZIP code coordinates |
| **Total** | **1,550,922** | |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- GCP account with Cloud SQL instance
- Grok API key OR Grok via Vertex AI

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/data-analysis-agent.git
cd data-analysis-agent
```

### 2. Set up Python environment

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Database
DB_HOST=your-cloud-sql-ip
DB_PORT=3306
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=olist_db

# GCP
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1

# LLM (choose one)
XAI_API_KEY=your-grok-api-key  # Direct Grok API
# OR use Vertex AI (requires gcloud auth)
```

### 4. Load the Olist dataset

Download from [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), unzip into `data/olist/`, then:

```bash
python scripts/load_olist.py
```

### 5. Run the backend

```bash
python main.py
# Runs on http://localhost:8000
```

### 6. Run the frontend

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:5173
```

### 7. Open the app

Visit `http://localhost:5173` and start asking questions!

---

## How It Works

### LangGraph Agent Flow

```
User question
      ↓
inspect_schema  →  reads all tables and columns from DB
      ↓
generate_sql    →  Grok AI writes MySQL query based on schema
      ↓
run_query       →  executes SQL against Cloud SQL
      ↓ (error?)
      ├── YES → generate_sql (retry with error context, max 3x)
      └── NO  → analyze
                    ↓
                 visualize → generates chart
                    ↓
                   END
```

### Why LangGraph?

LangGraph provides:
- **Retry loop** — bad SQL automatically gets fixed and retried
- **State management** — schema, SQL, data flows between nodes automatically
- **Separation of concerns** — each node does one job
- **Easy to extend** — add new nodes without touching existing code

### Why MCP?

MCP (Model Context Protocol) decouples tools from the agent:
- Agent doesn't care how the DB works — it just calls tools
- Swap databases without changing agent logic
- Same tools can be used by any MCP-compatible AI

### Real-time Streaming

FastAPI uses Server-Sent Events (SSE) to stream results:
```
status → sql → analysis → chart → data → done
```
The UI updates progressively as each step completes.

---

## Customizing for Your Data

The agent is designed to work with **any MySQL database**. Just update `dataset_config.yaml`:

```yaml
name: "Your Dataset Name"
database: "your_db"
description: "What your data is about"

tables:
  - name: your_table
    file: your_table.csv
    description: "What this table contains"
    key_columns: [id, name, date]

relationships:
  - "table_a.foreign_key → table_b.primary_key"

hints:
  - "Always filter by status = 'active'"
  - "Use created_at for date filtering"
```

No code changes needed — the agent reads the config at startup.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyze` | Run agent, streams SSE response |
| GET | `/health` | Health check |
| GET | `/dataset-info` | Current dataset info |
| GET | `/sample-questions` | Example questions |
| GET | `/docs` | Swagger UI |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| DB_HOST | ✅ | MySQL host IP |
| DB_PORT | ✅ | MySQL port (default 3306) |
| DB_USER | ✅ | MySQL username |
| DB_PASSWORD | ✅ | MySQL password |
| DB_NAME | ✅ | Database name |
| GCP_PROJECT_ID | ✅ | GCP project ID |
| GCP_REGION | ✅ | GCP region |
| XAI_API_KEY | ⚠️ | Grok API key (if using direct API) |

---

## Interview Talking Points

**"What is this project?"**
> A natural language data analysis agent that automatically writes SQL, analyzes results, and generates charts from plain English questions.

**"Why LangGraph?"**
> LangGraph provides the retry loop — when AI generates bad SQL, the graph automatically routes back to fix it. Without LangGraph this would be messy if/else code.

**"Why MCP?"**
> MCP decouples tools from the agent. The agent just calls `run_query` — it doesn't know or care how the database works. Swap the DB tool and nothing else changes.

**"How does streaming work?"**
> FastAPI yields SSE events as each agent node completes. React reads the stream chunk by chunk and updates the UI progressively.

**"How is it customizable?"**
> Everything dataset-specific lives in `dataset_config.yaml`. Change the config and the agent works with any MySQL database — no code changes needed.

---



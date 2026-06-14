import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from agent.graph import run_agent

app = FastAPI(
    title="Data Analysis Agent API",
    description="LangGraph + MCP powered data analysis agent",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets from React build
if os.path.exists("frontend/dist/assets"):
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

class AnalyzeRequest(BaseModel):
    question: str
    dataset: str = "olist"

def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

# ── API routes FIRST ─────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy", "agent": "data-analysis-agent", "version": "1.0.0"})

@app.get("/dataset-info")
async def dataset_info():
    import yaml
    with open("dataset_config.yaml") as f:
        config = yaml.safe_load(f)
    return JSONResponse({
        "name": config["name"],
        "description": config["description"],
        "tables": [t["name"] for t in config["tables"]],
        "hints": config.get("hints", [])[:3],
    })

@app.get("/sample-questions")
async def sample_questions():
    return JSONResponse({
        "questions": [
            "What are the top 5 product categories by total revenue?",
            "Show me monthly order trends for 2017",
            "Which sellers have the highest average review score?",
            "What is the average delivery time by state?",
            "Which payment methods are most popular?",
            "Show me the top 10 cities by number of customers",
            "What percentage of orders were delivered on time?",
            "Which product categories have the lowest review scores?",
        ]
    })

@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    async def stream():
        try:
            yield sse_event("status", {"node": "starting", "message": "Agent is starting..."})
            await asyncio.sleep(0.05)
            yield sse_event("status", {"node": "inspect_schema", "message": "Reading database schema..."})
            await asyncio.sleep(0.05)
            yield sse_event("status", {"node": "generate_sql", "message": "Generating SQL query..."})
            await asyncio.sleep(0.05)

            result = await run_agent(request.question)

            print(f"[main] chart_base64 length: {len(result.get('chart_base64', ''))}")
            print(f"[main] analysis length: {len(result.get('analysis', ''))}")
            print(f"[main] raw_data rows: {len(result.get('raw_data', []))}")

            yield sse_event("sql", {"sql": result.get("sql", ""), "message": "SQL query generated"})
            await asyncio.sleep(0.05)

            yield sse_event("status", {"node": "run_query", "message": f"Query returned {len(result.get('raw_data', []))} rows"})
            await asyncio.sleep(0.05)

            yield sse_event("analysis", {"text": result.get("analysis", ""), "row_count": len(result.get("raw_data", [])), "message": "Analysis complete"})
            await asyncio.sleep(0.05)

            chart_b64 = result.get("chart_base64", "")
            if chart_b64:
                yield sse_event("chart", {"image": chart_b64, "chart_type": result.get("chart_type", "bar"), "message": "Chart generated"})
                await asyncio.sleep(0.05)

            raw_data = result.get("raw_data", [])
            if raw_data:
                yield sse_event("data", {"rows": raw_data[:50], "total_rows": len(raw_data), "columns": list(raw_data[0].keys()), "message": "Data ready"})
                await asyncio.sleep(0.05)

            yield sse_event("done", {"message": "Analysis complete", "success": True})

        except Exception as e:
            import traceback
            print(f"[main] ERROR: {e}")
            print(traceback.format_exc())
            yield sse_event("error", {"message": str(e), "success": False})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Frontend routes LAST ─────────────────────────────

@app.get("/")
async def serve_root():
    dist_path = "frontend/dist/index.html"
    if os.path.exists(dist_path):
        return FileResponse(dist_path)
    return JSONResponse({"message": "Frontend not built. Run npm run build in frontend/"})

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    dist_path = "frontend/dist/index.html"
    if os.path.exists(dist_path):
        return FileResponse(dist_path)
    return JSONResponse({"message": "Frontend not built. Run npm run build in frontend/"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
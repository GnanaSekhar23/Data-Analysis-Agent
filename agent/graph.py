from langgraph.graph import StateGraph, END
from .state import AgentState
from . import nodes

def should_retry(state: AgentState) -> str:
    error       = state.get("error", "")
    retry_count = state.get("retry_count", 0)
    if error and retry_count < 3:
        print(f"[graph] retrying SQL (attempt {retry_count}/3)")
        return "generate_sql"
    return "analyze"

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("inspect_schema", nodes.inspect_schema)
    graph.add_node("generate_sql",   nodes.generate_sql)
    graph.add_node("run_query",      nodes.run_query_node)
    graph.add_node("analyze",        nodes.analyze)
    graph.add_node("visualize",      nodes.visualize)

    graph.set_entry_point("inspect_schema")
    graph.add_edge("inspect_schema", "generate_sql")
    graph.add_edge("generate_sql",   "run_query")
    graph.add_conditional_edges("run_query", should_retry, {
        "generate_sql": "generate_sql",
        "analyze":      "analyze",
    })
    graph.add_edge("analyze",   "visualize")
    graph.add_edge("visualize", END)

    return graph.compile()

async def run_agent(question: str) -> dict:
    graph = build_graph()
    initial_state = {
        "question":     question,
        "schema":       {},
        "hints":        [],
        "sql":          "",
        "raw_data":     [],
        "analysis":     "",
        "chart_base64": "",
        "chart_type":   "",
        "json_output":  {},
        "error":        "",
        "retry_count":  0,
        "messages":     [],
    }
    result = await graph.ainvoke(initial_state)
    return result
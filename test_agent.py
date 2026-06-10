import asyncio
from dotenv import load_dotenv
load_dotenv()

from agent.graph import run_agent

async def main():
    question = "What are the top 5 product categories by total revenue?"
    print(f"\nQuestion: {question}\n")

    result = await run_agent(question)

    print("\n--- SQL Generated ---")
    print(result["sql"])

    print("\n--- Analysis ---")
    print(result["analysis"])

    print("\n--- Chart ---")
    print("Chart generated:", bool(result["chart_base64"]))
    print("Chart type:", result["chart_type"])
    print("Rows returned:", len(result["raw_data"]))

asyncio.run(main())
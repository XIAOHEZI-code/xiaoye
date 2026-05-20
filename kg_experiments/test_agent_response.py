import sys
import os
import asyncio

sys.path.append(os.path.abspath('.'))

from src.reasoning.graph import create_worker_graph
from langchain_core.messages import SystemMessage

async def main():
    print("==================================================")
    print("      Testing Full Agent with KG-HyDE Retrieval   ")
    print("==================================================\n")
    
    query = "针对 test.pdf 的内容，请详细解释：为什么调质处理后 304/45双金属复合螺栓 的耐蚀性能会大幅度下降？其微观机理是什么？"
    print(f"【用户提问】: {query}\n")
    print("[Agent 正在思考并调用检索工具...]\n")
    
    graph = create_worker_graph()
    
    state = {
        "messages": [SystemMessage(content=query)],
        "step_satisfied": False,
        "past_steps": [],
        "ready_to_synthesize": False,
        "loop_count": 0,
        "reasoning": [],
        "thinking_config": {"type": "disabled"},
        "task_id": "test_agent"
    }
    
    try:
        # Use astream_events to see the thinking process
        final_answer = ""
        async for event in graph.astream_events(state, version="v2", config={"recursion_limit": 10}):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    final_answer += chunk.content
                    print(chunk.content, end="", flush=True)
            elif kind == "on_tool_start":
                tool_name = event["name"]
                print(f"\n\n[System: Calling tool '{tool_name}']\n")
            elif kind == "on_chain_end" and event["name"] == "evaluator":
                out = event["data"].get("output", {})
                if out and "messages" in out:
                    msgs = out["messages"]
                    for m in msgs:
                        if hasattr(m, "content") and "EVALUATOR_FEEDBACK" in m.content:
                            print(f"\n[Evaluator Feedback]: {m.content}\n")
                            
        print("\n\n==============================================")
    except Exception as e:
        print(f"Agent execution failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())

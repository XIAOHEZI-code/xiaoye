import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.agent.graph import compactor_node
from langchain_core.messages import ToolMessage, HumanMessage

def run_context_blackhole_test():
    print("=== [STRESS] Agent Context Overflow Blackhole Test ===")

    # 1. Simulate a malicious / overly dense tool return (e.g. 100,000 words CSV dump)
    massive_blackhole_text = "DataPoint,Value\n" * 50000 
    
    # 2. Build the state context representation
    state = {
        "messages": [
            HumanMessage(content="Query standard properties"),
            ToolMessage(content=massive_blackhole_text, tool_call_id="call_999", name="execute_metallurgy_python")
        ],
        "task_description": "Extract specific temperatures"
    }
    
    # 3. Fire the Context Compaction trigger
    print(f"Sending State Object of size: {len(massive_blackhole_text)} characters.")
    
    try:
        new_state = compactor_node(state)
        # Extract the processed latest message payload
        latest_processed_msg = new_state["messages"][-1]
        content_extracted = latest_processed_msg.content
        
        # 4. Evaluate Tombstone mechanism integrity 
        print(f"Resulting State Size Reduced to: {len(content_extracted)} characters.")
        
        assert "TOMBSTONE" in content_extracted or len(content_extracted) <= 4000, "Compactor Failed! Context bounds exceeded!"
        print("\n[✔] PASS: Microcompact node successfully severed the blackhole RAG text cascade.")
        
    except Exception as e:
        print(f"\n[✘] FAILED: Context engine threw exception: {e}")
        assert False

if __name__ == "__main__":
    run_context_blackhole_test()

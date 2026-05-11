import os
from langchain_core.messages import HumanMessage
from src.agent.swarm_coordinator import handle_complex_query
import uuid

def run_terminal_test():
    print("==================================================")
    print("   Xiaoye Swarm Agent - Terminal CLI Test (Redis) ")
    print("==================================================")
    print("Commands:")
    print("  /list           - Show all past/active sessions")
    print("  /resume <id>    - Resume a suspended session")
    print("  quit or exit    - Exit CLI\n")
    
    # Each session gets a unique team name / task board
    session_id = f"cli_session_{uuid.uuid4().hex[:6]}"
    print(f"[System] Initializing Redis TaskBoard for Session: {session_id}")
    print("[System] Swarm Coordinator Ready.\n")

    while True:
        try:
            user_input = input("\nUser Query > ")
            if user_input.lower() in ['exit', 'quit']:
                break
            if not user_input.strip():
                continue
                
            if user_input.startswith("/list"):
                from src.agent.task_board import TaskBoard
                sessions = TaskBoard.list_all_sessions()
                print("\n[System] Found available sessions in Redis:")
                for s in sessions:
                    print(f"  - {s}")
                if not sessions:
                    print("  (None)")
                continue
                
            if user_input.startswith("/resume"):
                parts = user_input.split(" ", 1)
                if len(parts) < 2:
                    print("[Error] Usage: /resume <session_id>")
                    continue
                target_session = parts[1].strip()
                print(f"\n[System] Re-hydrating Session: {target_session} ...")
                session_id = target_session
                
                from src.agent.swarm_coordinator import SwarmCoordinator
                import asyncio
                print("\n--- Swarm Coordinator Lifecycle Resume ---\n")
                coordinator = SwarmCoordinator(session_id)
                result = asyncio.run(coordinator.run())
                print(f"\n[System] Session Resumed & Completed. Result:\n{result}")
                continue
            
            print("\n--- Swarm Coordinator Lifecycle Start ---\n")
            
            # Directly hand off to the swarm async framework
            result = handle_complex_query(session_id, user_input)
            
            print("\n--- Swarm Coordinator Lifecycle End ---\n")
            
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n[Error] {e}")

if __name__ == "__main__":
    # Ensure environment variables are loaded
    from dotenv import load_dotenv
    load_dotenv()
    
    run_terminal_test()

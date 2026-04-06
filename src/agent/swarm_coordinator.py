import asyncio
import os
import json
from src.agent.task_board import TaskBoard
from src.core.config import settings

# ---------------------------------------------------------
# Claude Pattern: Coordinator Mode & Blackboard Spawning
# Replaces the tight AgentState loop. The manager splits
# the task, pushes it to board, and Idle-loops.
# ---------------------------------------------------------

class SwarmCoordinator:
    def __init__(self, session_id: str):
        self.board = TaskBoard(team_name=session_id)
        self.running = False

    async def run(self):
        """The Central Idle Loop"""
        self.running = True
        print(f"[Coordinator] Started Swarm loop for session: {self.board.team_name}")
        
        while self.running:
            # 1. Periodically check and unlock dependent tasks
            unassigned_tasks = self.board.get_unassigned_tasks()
            
            if unassigned_tasks:
                for task in unassigned_tasks:
                    print(f"[Coordinator] Sighted UNBLOCKED task: {task['task_id']}. Spawning Worker...")
                    # In a real environment, this might be submitting to a Celery queue
                    # Here we spawn an asyncio task representing an independent process
                    asyncio.create_task(self.spawn_worker(task['task_id']))
                    
            # 2. Check if entire board is COMPLETED (End condition)
            if self._is_all_completed():
                print("[Coordinator] All tasks COMPLETED! Coordinator winding down.")
                break
                
            # 3. Claude Pattern: Idle Sleep (0 CPU spin)
            await asyncio.sleep(2.0)
            
        return self._aggregate_results()

    async def spawn_worker(self, task_id: str):
        """Simulates an independent Agent RAG process."""
        owner_name = f"Worker_{os.getpid()}_{task_id[-4:]}"
        if not self.board.claim_task(task_id, owner_name):
            return # Someone else got it

        print(f"[{owner_name}] Claimed task {task_id}. Processing independently...")
        task_data = self.board.get_task(task_id)
        
        # -----------------------------------------------------------------
        # Real invocation of the Thinned-down graph.py Worker pipeline here
        # For prototype, we simulate network/LLM delay
        # -----------------------------------------------------------------
        from src.agent.graph import run_worker_pipeline
        result = await run_worker_pipeline({"task_description": task_data["description"]})
        
        print(f"[{owner_name}] Task {task_id} done. Writing back to Blackboard.")
        self.board.mark_completed(task_id, result)

    def _is_all_completed(self) -> bool:
        """Helper to determine overall completion."""
        keys = self.board.r.keys(f"{self.board.prefix}:task_*")
        if not keys: return False
        
        for key in keys:
            t = json.loads(self.board.r.get(key))
            if t["status"] != "COMPLETED":
                return False
        return True

    def _aggregate_results(self) -> str:
        """Synthesizer Step - merge all results when finished."""
        out = []
        keys = self.board.r.keys(f"{self.board.prefix}:task_*")
        for key in keys:
             t = json.loads(self.board.r.get(key))
             out.append(f"Task: {t['description']}\nResult: {t['result']}")
        return "\n\n".join(out)

# Entry point for the user's complex intention
def handle_complex_query(session_id: str, query: str):
    coordinator = SwarmCoordinator(session_id)
    
    # 真正的 UltraPlan LLM 交互式输出 (Human-in-the-Loop)
    from src.agent.ultraplan import UltraPlanner
    planner = UltraPlanner()
    
    plan = planner.interactive_review_and_edit(query)
    
    # 若在交互门阀中选择了 Cancel，则直接刹车丢弃
    if not plan:
        print("\n[System] Swarm mobilization halted by user decree.")
        return "Operation Cancelled."
    
    task_id_map = {}
    
    # 构建真实任务黑板，实现无缝拓扑映射
    print("\n[BlackBoard] Engraving tasks into Redis clusters:")
    for t in plan.tasks:
        real_depends_on = [task_id_map[dep] for dep in t.depends_on if dep in task_id_map]
        board_task = coordinator.board.create_task(
            description=t.description, 
            depends_on=real_depends_on
        )
        task_id_map[t.task_id] = board_task["task_id"]
        print(f"  -> Spawning: [{board_task['task_id']}] {t.description} (Blocked By: {real_depends_on})")
        
    print("\n")
    
    # Run the swarm with a basic exception cage to map real Claude rolling errors
    try:
        final_output = asyncio.run(coordinator.run())
        print("\n\n==== Swarm Synthesizer Final Result ====\n")
        print(final_output)
        return final_output
    except Exception as e:
        print(f"\n[FATAL CRASH] The Hive Mind encountered an irrecoverable chain break: {e}")
        print("[!] A true Architect would extract this stacktrace and feed it back to Seed Plan generation.")
        print("[!] (Rolling Repair System initiated... please stand by or manually re-issue a draft).")
        return f"[Failed Execution] {e}"

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import asyncio
from src.agent.task_board import TaskBoard

async def worker_node(worker_id: int, task_ids: list, session_name: str):
    board = TaskBoard(session_name)
    successes = 0
    # Simulate aggressive "Herd" scanning pattern
    for t_id in task_ids:
        # Atomic lock claim
        if board.claim_task(t_id, f"Worker_{worker_id}"):
            successes += 1
            # Simulate work cycle
            await asyncio.sleep(0.01)
            board.mark_completed(t_id, f"Result_from_worker_{worker_id}")
    return successes

async def run_redis_herd_test():
    print("=== [STRESS] Redis Optimistic Lock Herd Test ===")
    session_id = "stress_test_herd"
    board = TaskBoard(session_id)
    
    # 1. Clean previous runs
    keys = board.r.keys(f"{board.prefix}:*")
    if keys:
        board.r.delete(*keys)

    # 2. Spawn 50 tasks
    task_keys = []
    print("Spawning 50 tasks on Blackboard...")
    for i in range(50):
        t = board.create_task(description=f"Math calculation node #{i}")
        task_keys.append(t['task_id'])

    # 3. Release the Herd (200 Workers)
    print("Releasing 200 ravenous Swarm Workers simultaneously...")
    tasks = []
    for w in range(200):
        tasks.append(asyncio.create_task(worker_node(w, task_keys.copy(), session_id)))

    # Wait for all workers to finish their collision battle
    worker_results = await asyncio.gather(*tasks)
    
    total_claims = sum(worker_results)
    print(f"\n[Metrics] Total successful ATOMIC claims recorded: {total_claims}")
    
    # 4. Verification Check
    # Even with 200 concurrent threads, strict Redis Watch tracking means EXACTLY 50 claims occur
    # Not 49 (dropped), not 51 (double claim).
    assert total_claims == 50, f"RACE CONDITION FAILED! Expected 50 claims, got {total_claims}"
    
    # Check all are completed
    unassigned = board.get_unassigned_tasks()
    assert len(unassigned) == 0, "Some tasks were mysteriously left behind!"
    
    print("\n[✔] PASS: Master Swarm Lock perfectly bypassed TOCTOU vulnerabilities.")

if __name__ == "__main__":
    asyncio.run(run_redis_herd_test())

import sys
import os
import concurrent.futures
import time
import uuid
import redis

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.agent.task_board import TaskBoard

def claim_worker(board: TaskBoard, task_id: str, worker_id: int) -> bool:
    """A single worker trying to claim the task."""
    agent_name = f"Worker_{worker_id}"
    try:
        success = board.claim_task(task_id, agent_name)
        return success
    except Exception as e:
        print(f"Worker {worker_id} encountered an error: {e}")
        return False

def test_redis_claim_race_condition():
    print("=== [STRESS] TaskBoard Redis Optimistic Locking Concurrent Claim Test ===")
    
    # 1. Initialize TaskBoard
    team_name = f"stress_test_{uuid.uuid4().hex[:8]}"
    board = TaskBoard(team_name=team_name)
    
    # Clear any old data
    keys = board.r.keys(f"{board.prefix}:*")
    if keys:
        board.r.delete(*keys)

    # 2. Create a single task
    task = board.create_task("High Concurrency Target Task")
    # Actually create_task makes it "TODO" if no depends_on
    task_id = task["task_id"]
    print(f"Created single target task: {task_id}")

    # Set up concurrency
    concurrency_level = 50
    print(f"Releasing {concurrency_level} threads to simultaneously claim this exact task...")

    successes = 0
    failures = 0

    # 3. Use ThreadPoolExecutor to blast the Redis server
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency_level) as executor:
        # We use a barrier/sleep to try and align the start time as much as possible
        time.sleep(0.5) 
        
        futures = [executor.submit(claim_worker, board, task_id, i) for i in range(concurrency_level)]
        
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res is True:
                successes += 1
            else:
                failures += 1

    print(f"\n[Metrics] Claim Attempts:")
    print(f"  - Total Workers: {concurrency_level}")
    print(f"  - Successful Claims: {successes}")
    print(f"  - Rejected Claims (WatchError/Owned): {failures}")

    # 4. Verify exactly ONE succeeded.
    try:
        assert successes == 1, f"CRITICAL: Failed TOCTOU safety! {successes} threads somehow claimed the same task."
        assert failures == concurrency_level - 1, f"Mismatched failures: {failures}"
        
        # 5. Verify the actual task data in Redis
        final_task = board.get_task(task_id)
        assert final_task["status"] == "IN_PROGRESS", "Task should be marked as IN_PROGRESS"
        assert final_task["owner"] is not None, "Task should have an owner assigned"
        print(f"\n[Validation] Task securely owned by: {final_task['owner']}")
        print("\n[✔] PASS: Redis WATCH/MULTI Optimistic Locking guarantees zero race conditions.")
        
    finally:
        # Cleanup
        keys = board.r.keys(f"{board.prefix}:*")
        if keys:
            board.r.delete(*keys)

if __name__ == "__main__":
    test_redis_claim_race_condition()

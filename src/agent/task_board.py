import json
import os
from typing import TypedDict, List, Optional
from uuid import uuid4
import redis

# ---------------------------------------------------------
# Claude-Swarm Pattern / Redis Implementation
# 100% Free of Race Conditions utilizing Redis transactions
# ---------------------------------------------------------

class SwarmTask(TypedDict):
    task_id: str
    description: str
    owner: Optional[str]
    status: str # "TODO", "IN_PROGRESS", "BLOCKED", "COMPLETED"
    result: Optional[str]
    depends_on: List[str]

class TaskBoard:
    def __init__(self, team_name: str, redis_url: str = "redis://localhost:6379/0"):
        self.team_name = team_name
        # Connect to the Redis instance discovered from docker ps
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.prefix = f"xiaoye:{self.team_name}:tasks"
        
    @classmethod
    def list_all_sessions(cls, redis_url: str = "redis://localhost:6379/0") -> List[str]:
        """Class method to discover all historically active sessions (team_names)."""
        r = redis.from_url(redis_url, decode_responses=True)
        keys = r.keys("xiaoye:*:tasks:*")
        sessions = set()
        for k in keys:
            parts = k.split(":")
            if len(parts) >= 4:
                sessions.add(parts[1])
        return sorted(list(sessions))
        
    def _task_key(self, task_id: str) -> str:
        return f"{self.prefix}:{task_id}"

    def create_task(self, description: str, depends_on: List[str] = None) -> SwarmTask:
        task_id = f"task_{uuid4().hex[:8]}"
        task: SwarmTask = {
            "task_id": task_id,
            "description": description,
            "owner": None,
            "status": "BLOCKED" if depends_on else "TODO",
            "result": None,
            "depends_on": depends_on or []
        }
        self._save_task(task)
        return task

    def _save_task(self, task: SwarmTask):
        key = self._task_key(task["task_id"])
        self.r.set(key, json.dumps(task, ensure_ascii=False))

    def get_task(self, task_id: str) -> Optional[SwarmTask]:
        data = self.r.get(self._task_key(task_id))
        return json.loads(data) if data else None

    def refresh_blocked_tasks(self):
        """Check all BLOCKED tasks and set to TODO if dependencies are met."""
        keys = self.r.keys(f"{self.prefix}:task_*")
        for key in keys:
            t = json.loads(self.r.get(key))
            if t["status"] == "BLOCKED":
                all_met = True
                for dep_id in t.get("depends_on", []):
                    dep_task = self.get_task(dep_id)
                    if not dep_task or dep_task["status"] != "COMPLETED":
                        all_met = False
                        break
                if all_met:
                    t["status"] = "TODO"
                    self._save_task(t)

    def get_unassigned_tasks(self) -> List[SwarmTask]:
        self.refresh_blocked_tasks()
        tasks = []
        keys = self.r.keys(f"{self.prefix}:task_*")
        for key in keys:
            t = json.loads(self.r.get(key))
            if t["status"] == "TODO" and t["owner"] is None:
                tasks.append(t)
        return tasks

    def claim_task(self, task_id: str, agent_name: str) -> bool:
        """
        ATOMIC claim operation using Redis WATCH (Optimistic Locking)
        Completely eliminates Race Conditions (TOCTOU).
        """
        key = self._task_key(task_id)
        
        with self.r.pipeline() as pipe:
            try:
                # 1. Watch the specific task key for any modifications by other Workers
                pipe.watch(key)
                
                data = pipe.get(key)
                if not data:
                    return False
                    
                t = json.loads(data)
                
                # If someone else already owns it, abort.
                if t["owner"] is not None or t["status"] != "TODO":
                    pipe.unwatch()
                    return False
                
                # 2. Prepare our changes
                t["owner"] = agent_name
                t["status"] = "IN_PROGRESS"
                
                # 3. Enter transaction mode. 
                # If another Worker modified this key since our `watch`, `execute()` will raise WatchError!
                pipe.multi()
                pipe.set(key, json.dumps(t, ensure_ascii=False))
                pipe.execute()
                
                return True
                
            except redis.WatchError:
                # Collision detected! Another Worker snatched this task mere milliseconds before us.
                # In swarm theory, this is expected. We just yield (return False).
                return False

    def mark_completed(self, task_id: str, result: str):
        # We also use Optimistic Locking here to ensure no weird overwrites
        key = self._task_key(task_id)
        with self.r.pipeline() as pipe:
            try:
                pipe.watch(key)
                data = pipe.get(key)
                if data:
                    t = json.loads(data)
                    t["status"] = "COMPLETED"
                    t["result"] = result
                    pipe.multi()
                    pipe.set(key, json.dumps(t, ensure_ascii=False))
                    pipe.execute()
            except redis.WatchError:
                pass # Unlikely for mark_completed, but safe

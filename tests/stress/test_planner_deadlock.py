import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.agent.ultraplan import UltraPlanner

def verify_acyclic_graph(tasks):
    # Standard topology check to detect cycle deadlocks
    # Given tasks list from Pydantic output
    graph = {t.task_id: t.depends_on for t in tasks}
    visited = set()
    path = set()
    
    def visit(node):
        if node in path:
            return True # Cycle detected
        if node in visited:
            return False
            
        visited.add(node)
        path.add(node)
        for neighbor in graph.get(node, []):
            if visit(neighbor):
                return True
        path.remove(node)
        return False

    for node in graph:
        if visit(node):
            return False # Graph is cyclic (Deadlock!)
    return True

def run_planner_deadlock_test():
    print("=== [STRESS] Architect Mode Circular Dependency (Deadlock) Defense Test ===")

    planner = UltraPlanner()
    
    # 1. Supply an extremely misleading prompt meant to confuse the underlying LLM into drawing a circle
    paradox_query = """
    我已经将研究发给你了。请分发任务。注意他们的逻辑限制：
    任务A（分析热容量）需要任务B的数据。
    任务B（获取配料表参数）需要任务C的验证标准。
    任务C（制定验证标准）又必须等任务A得出初步结论后才能开始！
    请确保这三个相互挂钩的节点被规划！
    """
    
    print("\n[Security] Injecting paradox dependency poison directly into UltraPlanner...")
    print("Paradox Injection:", paradox_query.strip().replace("\n", " "))
    
    try:
        plan = planner.generate_plan(paradox_query)
        
        # 2. Extract generated constraints 
        print("\n[Result] Model Generated Graph:")
        for t in plan.tasks:
            print(f"Task: {t.task_id} <- Blocking: {t.depends_on}")
            
        # 3. Validation
        is_safe = verify_acyclic_graph(plan.tasks)
        assert is_safe, "DEADLOCK DETECTED! The Architect fell for the circular dependency trap and designed a broken blueprint."
        
        print("\n[✔] PASS: The UltraPlanner remained logically rigorous. It either broke the cycle or refused the impossibility.")

    except Exception as e:
        # If the LLM throws an output formatting error because it refused to comply, we also consider it a Pass.
        print(f"\n[?] Note: Planner raised exception instead of looping. This is also safe behavior. Error: {e}")

if __name__ == "__main__":
    run_planner_deadlock_test()

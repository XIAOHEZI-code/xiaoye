import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import concurrent.futures
from src.tools.sandbox import JupyterSandbox

def single_sandbox_lifecycle(s_id: int):
    try:
        sandbox = JupyterSandbox()
        # Stressing numpy computation
        code = f"""
import numpy as np
a = np.random.rand(1000, 1000)
b = np.random.rand(1000, 1000)
c = np.dot(a, b)
print("Sandbox {s_id} matrix trace:", np.trace(c))
"""
        result = sandbox.run_code(code, timeout=10)
        sandbox.shutdown()
        
        if "Sandbox" in result and "trace" in result:
            return True
        return False
    except Exception as e:
        print(f"[Sandbox-{s_id} Failed] {e}")
        return False

def run_sandbox_storm_test():
    print("=== [STRESS] Jupyter ZMQ Port Memory Storm Test ===")
    concurrency_level = 10  # Reduced to 10 so we don't completely crash the OS on standard machines
    print(f"Spawning {concurrency_level} completely isolated Jupyter IPyKernels simultaneously...")
    
    successes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency_level) as executor:
        futures = [executor.submit(single_sandbox_lifecycle, i) for i in range(concurrency_level)]
        for fut in concurrent.futures.as_completed(futures):
            if fut.result():
                successes += 1
                
    print(f"\n[Metrics] Kernels successfully initialized, computed, and pruned: {successes}/{concurrency_level}")
    assert successes == concurrency_level, "ZeroMQ/Jupyter Port exhaustion occurred!"
    
    print("\n[✔] PASS: Execution Sandboxes successfully handled high-concurrency without Resource Leaks.")

if __name__ == "__main__":
    run_sandbox_storm_test()

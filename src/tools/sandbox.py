import sys
import jupyter_client
import base64
import queue
import time
import threading
import re
from typing import Dict, Any
from src.core.logger import setup_logger

logger = setup_logger("xiaoye.sandbox")

class JupyterSandbox:
    """
    A bespoke stateful Code Interpreter.
    Eliminates the need for pulling heavy OpenInterpreter stacks.
    Keeps an alive connection to an isolated local Kernel via ZMQ.
    Implements an idle-timeout watchdog for automatic cleanup.
    """
    def __init__(self, idle_timeout: float = 600.0):
        self.idle_timeout = idle_timeout
        self.last_used = time.time()
        self.is_alive = True

        logger.info("Initializing stateful Python Kernel...")
        self.km = jupyter_client.KernelManager(kernel_name='python3')
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=15)
        
        # Pre-inject SciencePlots styling and ignore warnings silently
        logger.info("Pre-injecting SciencePlots styling and warnings filter into Kernel...")
        pre_inject_code = (
            "try:\n"
            "    import warnings\n"
            "    warnings.simplefilter('ignore')\n"
            "except Exception:\n"
            "    pass\n"
            "try:\n"
            "    import matplotlib.pyplot as plt\n"
            "    import scienceplots\n"
            "    plt.style.use(['science', 'no-latex'])\n"
            "except Exception:\n"
            "    pass\n"
        )
        msg_id = self.kc.execute(pre_inject_code)
        # Drain messages for styling execution
        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=2)
                if msg['parent_header'].get('msg_id') == msg_id:
                    if msg['header']['msg_type'] == 'status' and msg['content'].get('execution_state') == 'idle':
                        break
            except queue.Empty:
                break
        try:
            self.kc.get_shell_msg(timeout=1)
        except queue.Empty:
            pass
        
        # Start background watchdog thread to clean up inactive kernels
        self.watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog.start()
        
        logger.info("Stateful Python Kernel initialized successfully with 10-minute watchdog and SciencePlots styling.")

    def _watchdog_loop(self):
        """Periodically checks if the kernel has been inactive for longer than the idle timeout."""
        while self.is_alive:
            time.sleep(30)
            if not self.is_alive:
                break
            idle_duration = time.time() - self.last_used
            if idle_duration > self.idle_timeout:
                logger.info(f"Kernel inactivity timeout ({idle_duration:.1f}s > {self.idle_timeout}s) reached. Triggering auto-destruction.")
                self.shutdown()
                break

    def run_code(self, code: str, timeout: int = 60) -> str:
        """
        Executes code into the live Kernel, intercepts STDOUT, STDERR, and Image Blobs.
        """
        self.last_used = time.time()
        logger.info(f"Sandbox executing code (length={len(code)}):\n{code.strip()}")

        msg_id = self.kc.execute(code)
        output_chunks = []
        got_idle = False

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=timeout)
            except queue.Empty:
                logger.warning("Kernel execution timed out.")
                output_chunks.append("ERROR: Kernel execution timed out.")
                break

            # Only process messages belonging to our execution request
            if msg['parent_header'].get('msg_id') != msg_id:
                continue

            msg_type = msg['header']['msg_type']
            content = msg['content']

            if msg_type == 'status' and content.get('execution_state') == 'idle':
                # All output for this execution has been flushed — safe to exit
                got_idle = True
                break

            if msg_type == 'stream':
                text = content['text']
                if content.get('name') == 'stderr':
                    # Filter out warning lines (case-insensitive check for warning/UserWarning/missing glyphs)
                    lines = text.splitlines()
                    filtered_lines = []
                    for line in lines:
                        if "warning" in line.lower() or "missing from font" in line:
                            logger.info(f"Filtered out warning line from stderr: {line}")
                            continue
                        filtered_lines.append(line)
                    if filtered_lines:
                        text = "\n".join(filtered_lines) + "\n"
                        output_chunks.append(text)
                        logger.info(f"[Kernel STDERR] {text.strip()}")
                else:
                    output_chunks.append(text)
                    logger.info(f"[Kernel STDOUT] {text.strip()}")

            elif msg_type == 'error':
                err = "\n".join(content['traceback'])
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                clean_err = ansi_escape.sub('', err)
                output_chunks.append("ERROR:\n" + clean_err)
                logger.error(f"[Kernel Execution Error] {clean_err.strip()}")

            elif msg_type in ('display_data', 'execute_result'):
                data = content.get('data', {})
                if 'text/plain' in data:
                    output_chunks.append(data['text/plain'])
                    logger.info(f"[Kernel Result] {data['text/plain'].strip()}")
                if 'image/png' in data:
                    b64_image = data['image/png']
                    logger.info(f"[Kernel Rich Media] Sighted an image. Base64 length: {len(b64_image)}")
                    
                    # Local saving logic under data/
                    import os
                    from datetime import datetime
                    from src.tooling.definitions import current_task_id
                    
                    task_id = current_task_id.get() or "default"
                    clean_task_id = task_id.replace("sub_", "")
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"plot_{clean_task_id}_{timestamp_str}.png"
                    
                    save_dir = "data"
                    os.makedirs(save_dir, exist_ok=True)
                    filepath = os.path.join(save_dir, filename)
                    
                    try:
                        with open(filepath, "wb") as f:
                            f.write(base64.b64decode(b64_image))
                        logger.info(f"Saved sandbox plot to disk: {filepath}")
                        output_chunks.append(f"\n> 💾 **学术图表已保存至本地：** `{filepath}`\n")
                    except Exception as save_err:
                        logger.error(f"Failed to save sandbox plot to disk: {save_err}")

                    output_chunks.append(f"\n![学术图表](data:image/png;base64,{b64_image})\n")
                    output_chunks.append(f"\n[System: Sighted an Image (PNG). Base64 snippet: {b64_image[:30]}...]\n")

        # Drain the shell reply so it doesn't leak into the next run_code call
        if got_idle:
            try:
                self.kc.get_shell_msg(timeout=3)
            except queue.Empty:
                pass

        final_out = "\n".join(output_chunks).strip()
        logger.info(f"Sandbox execution complete. Produced {len(final_out)} chars of output.")
        return final_out if final_out else "Execution succeeded without output."

    def shutdown(self):
        if not self.is_alive:
            return
        self.is_alive = False
        try:
            self.kc.stop_channels()
            self.km.shutdown_kernel()
        except Exception as e:
            logger.error(f"Error during kernel shutdown: {e}")
            
        logger.info("Kernel naturally terminated and resources released.")
        
        # Clear the global instance so it can be re-created on next call
        global _sandbox_instance
        if _sandbox_instance is self:
            _sandbox_instance = None

# Global Singleton for the Tool
_sandbox_instance = None
def get_sandbox() -> JupyterSandbox:
    global _sandbox_instance
    if _sandbox_instance is None:
        _sandbox_instance = JupyterSandbox()
    return _sandbox_instance

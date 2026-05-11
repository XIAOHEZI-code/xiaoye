import sys
import jupyter_client
import base64
import queue
from typing import Dict, Any

class JupyterSandbox:
    """
    A bespoke stateful Code Interpreter.
    Eliminates the need for pulling heavy OpenInterpreter stacks.
    Keeps an alive connection to an isolated local Kernel via ZMQ.
    """
    def __init__(self):
        # We start a python3 kernel.
        # Note: In Phase 2, this will bridge to a Remote Docker Kernel.
        self.km = jupyter_client.KernelManager(kernel_name='python3')
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=15)
        print("[JupyterSandbox] Stateful Python Kernel initialized successfully.")

    def run_code(self, code: str, timeout: int = 60) -> str:
        """
        Executes code into the live Kernel, intercepts STDOUT, STDERR, and Image Blobs.

        Completion strategy: use iopub 'status: idle' as the primary signal that
        all output has been flushed. This avoids the race condition where the shell
        reply arrives before stdout/stderr iopub messages.
        """
        import re
        msg_id = self.kc.execute(code)

        output_chunks = []
        got_idle = False

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=timeout)
            except queue.Empty:
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
                output_chunks.append(content['text'])

            elif msg_type == 'error':
                err = "\n".join(content['traceback'])
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                output_chunks.append("ERROR:\n" + ansi_escape.sub('', err))

            elif msg_type in ('display_data', 'execute_result'):
                data = content.get('data', {})
                if 'text/plain' in data:
                    output_chunks.append(data['text/plain'])
                if 'image/png' in data:
                    b64_image = data['image/png']
                    output_chunks.append(f"\n[System: Sighted an Image (PNG). Base64 snippet: {b64_image[:30]}...]\n")

        # Drain the shell reply so it doesn't leak into the next run_code call
        if got_idle:
            try:
                self.kc.get_shell_msg(timeout=3)
            except queue.Empty:
                pass

        final_out = "\n".join(output_chunks).strip()
        return final_out if final_out else "Execution succeeded without output."

    def shutdown(self):
        self.kc.stop_channels()
        self.km.shutdown_kernel()
        print("[JupyterSandbox] Kernel naturally terminated.")

# Global Singleton for the Tool
_sandbox_instance = None
def get_sandbox() -> JupyterSandbox:
    global _sandbox_instance
    if _sandbox_instance is None:
        _sandbox_instance = JupyterSandbox()
    return _sandbox_instance

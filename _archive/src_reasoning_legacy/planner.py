import os
from pydantic import BaseModel, Field
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from src.core.config import settings

# ---------------------------------------------------------
# Claude Pattern: Ultraplan (Architect Mode) V2
# Evolved from a simple single-shot struct into a dynamic
# Interactive State Machine w/ Human-In-The-Loop controls.
# ---------------------------------------------------------

class TaskDefinition(BaseModel):
    task_id: str = Field(description="Unique short identifier for the task, e.g., T1, T2")
    description: str = Field(description="Detailed actionable description of what needs to be researched or executed")
    depends_on: List[str] = Field(default=[], description="List of task_ids that must be completed before this task can start")

class UltraPlan(BaseModel):
    tasks: List[TaskDefinition] = Field(description="List of all subtasks needed to fulfill the user request")

class UltraPlanner:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="qwen-max",
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
            temperature=0.1
        )
        self.planner_llm = self.llm.with_structured_output(UltraPlan, method="function_calling")
        
        # Physically separating prompt domains (Architectural decoupled injection)
        prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'ultraplan.txt')
        with open(prompt_path, 'r', encoding='utf-8') as f:
            self.system_prompt = f.read()

    def generate_plan(self, user_query: str, seed_feedback: str = None) -> UltraPlan:
        """Core AI dissection loop that supports seed re-prompting (Drafting changes)."""
        content = f"User Request: {user_query}"
        
        if seed_feedback:
            content += f"\n\n[HUMAN/SYSTEM FEEDBACK FOR REVISION]:\n{seed_feedback}\n\nPlease regenerate the plan topology incorporating this vital refinement!"
            
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=content)
        ]
        
        plan = self.planner_llm.invoke(messages)
        return plan

    def interactive_review_and_edit(self, user_query: str) -> Optional[UltraPlan]:
        """
        The hallmark of Claude Code: Human-In-The-Loop Approval Gates.
        Halts Swarm propagation until the mortal overseer greenlights the topological map.
        Contains an embedded state machine allowing users to loop feedback (Draft Refinements).
        """
        print("\n[UltraPlanner] Deep Cognition Activated. Charting Architectural Topography...")
        current_plan = self.generate_plan(user_query)
        
        while True:
            print("\n================= INTERACTIVE ARCHITECT REVIEW =================")
            print("The Architect drafted the following Multi-Agent Node Topology:")
            for t in current_plan.tasks:
                deps = f"(Blocked By: {t.depends_on})" if t.depends_on else "(Parallel Root)"
                print(f"  [{t.task_id}] {deps} -> {t.description}")
            print("================================================================")
            
            print("\n[Decision Gate]")
            user_input = input("Approve this plan? [Y]es / [C]ancel / <Type instructions to re-draft> > ").strip()
            
            if user_input.lower() in ('y', 'yes', ''):
                print("\n[✔] Master Override Authorized. Releasing the Swarm clusters!")
                return current_plan
            elif user_input.lower() in ('c', 'cancel', 'exit', 'quit'):
                print("\n[-] Mission Aborted. The diagram has been shredded.")
                return None
            else:
                print("\n[!] Injecting human insights as Seed Plan Feedback. Brainstorming alternate topologies...")
                current_plan = self.generate_plan(user_query, seed_feedback=user_input)

import os
import sys

base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(base_dir, '.env'))

from orchestrator import build_agent
from langchain_core.messages import HumanMessage

def run():
    agent = build_agent()
    task = "přidej u produktu tričko klid v neklidu 2.0 5x Natural Raw XS"
    print(f"Task: {task}")
    
    result = agent.invoke({
        "messages": [HumanMessage(content=task)],
        "current_specialist": "",
        "task_summary": "",
        "use_memory": False,
        "publish_to_wp": False,
        "pending_steps": [],
        "current_plan": "",
        "step_results": [],
    })
    
    # Print what the agent actually decided
    ai_msgs = [m for m in result["messages"] if m.__class__.__name__ == "AIMessage"]
    if ai_msgs:
        print("\nAgent said:\n", ai_msgs[-1].content)
    
    print("\nResult Data:\n")
    print("step_results:", result.get("step_results"))

if __name__ == "__main__":
    run()

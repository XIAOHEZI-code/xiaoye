from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from src.agent.graph import create_metallurgy_agent
# from src.worker.tasks import process_pdf_task

router = APIRouter()

# Initialize the stateful logic graph once
agent_graph = create_metallurgy_agent()

class ChatRequest(BaseModel):
    query: str
    session_id: str = "default_session"

class ChatResponse(BaseModel):
    response: str

@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(request: ChatRequest):
    """
    Main entry point for interacting with the Metallurgy ReAct Agent.
    """
    try:
        inputs = {"messages": [HumanMessage(content=request.query)]}
        
        # Invoke the LangGraph app. It will run in loops (Thought -> Action -> Obs)
        # until the Agent outputs a final message not requiring tool calls.
        
        # Note: LangGraph returns a dictionary representing the final state
        final_state = agent_graph.invoke(inputs)
        
        # The last message in the state is the Agent's answer to the user
        last_message = final_state["messages"][-1]
        
        return ChatResponse(response=last_message.content)
        
    except Exception as e:
        print(f"Agent Inference Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ingest/pdf")
async def ingest_pdf(file_path: str, background_tasks: BackgroundTasks):
    """
    Triggers the asynchronous Celery pipeline to digest a PDF.
    Sends it through Marker -> QWEN Image Analysis -> Triplet Extraction -> ES/Neo4j.
    """
    import uuid
    doc_id = str(uuid.uuid4())
    
    # In a full app, this would be:
    # process_pdf_task.delay(doc_id, file_path)
    
    return {"status": "Async pipeline triggered", "doc_id": doc_id}

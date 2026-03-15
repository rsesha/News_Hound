# mypy: disable - error - code = "no-untyped-def,misc"
import pathlib
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import sys
import os
import json
import asyncio

def safe_print(text, **kwargs):
    """Safely prints text to handle Windows console encoding issues and long strings."""
    try:
        # Avoid flush/end quirks and truncate extremely long logs
        clean_kwargs = {k: v for k, v in kwargs.items() if k not in ['flush', 'end']}
        msg = str(text)
        if len(msg) > 5000:
            msg = msg[:5000] + "... [TRUNCATED]"
            
        print(msg, **clean_kwargs)
    except:
        try:
            clean_text = str(text).encode('ascii', 'ignore').decode('ascii')[:5000]
            print(clean_text)
        except:
            pass

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from agent.research_agent import run_research_agent

# Define the FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    messages: List[Dict[str, Any]]
    initial_search_query_count: Optional[int] = 3
    max_research_loops: Optional[int] = 3
    reasoning_model: Optional[str] = "qwen35-small"
    instructions: Optional[str] = None

@app.post("/chat")
async def chat(request: QueryRequest):
    """Process a chat query and stream results"""
    
    async def event_generator():
        # Create a queue to relay events from the agent task
        queue = asyncio.Queue()
        
        # Define a wrapper to put events into the queue
        async def agent_task():
            try:
                async for event in run_research_agent(
                    messages=request.messages,
                    initial_search_query_count=request.initial_search_query_count or 3,
                    max_research_loops=request.max_research_loops or 3,
                    reasoning_model=request.reasoning_model or "qwen35-small",
                    instructions=request.instructions
                ):
                    await queue.put(event)
                await queue.put({"event": "done", "data": {}})
            except Exception as e:
                safe_print(f"ERROR in research_agent: {str(e)}")
                await queue.put({"event": "error", "data": str(e)})
                await queue.put({"event": "done", "data": {}})

        # Start the agent task in the background
        task = asyncio.create_task(agent_task())
        
        try:
            while True:
                try:
                    # Wait for an event with a timeout for heartbeats
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    if event.get("event") == "done":
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
        finally:
            task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

def create_frontend_router(build_dir="../frontend/dist"):
    """Creates a router to serve the React frontend."""
    build_path = pathlib.Path(__file__).parent.parent.parent / build_dir

    if not build_path.is_dir() or not (build_path / "index.html").is_file():
        print(
            f"WARN: Frontend build directory not found or incomplete at {build_path}. Serving frontend will likely fail."
        )
        from starlette.routing import Route
        async def dummy_frontend(request):
            return Response(
                "Frontend not built. Run 'npm run build' in the frontend directory.",
                media_type="text/plain",
                status_code=503,
            )
        return Route("/{path:path}", endpoint=dummy_frontend)

    return StaticFiles(directory=build_path, html=True)

# Mount the frontend under /app
app.mount(
    "/app",
    create_frontend_router(),
    name="frontend",
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=2024)


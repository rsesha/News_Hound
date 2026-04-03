# NewsHound Backend

The Python/FastAPI backend powering the NewsHound research engine. It orchestrates multi-source web searches, runs LLM-based reasoning, and streams results to the frontend in real time.

---

## Directory Structure

```
backend/
├── main.py                  # Thin entry point – delegates to uvicorn
└── research_engine/
    ├── app.py               # FastAPI app, all HTTP endpoints, SSE streaming
    ├── research_agent.py    # Core async pipeline: query → search → synthesize
    ├── graph.py             # LangGraph state machine (alternative/debug path)
    ├── graph_debug.py       # Extended debug version of the LangGraph graph
    ├── state.py             # TypedDict state schemas for LangGraph
    ├── configuration.py     # Pydantic config object (reads from .env)
    ├── local_llm.py         # LLM abstraction: local (Llama-Swap/Ollama) + Gemini
    ├── prompts.py           # All LLM prompt templates
    ├── prompts_bak.py       # Prompt backup / experimentation
    ├── tools_and_schemas.py # Pydantic schemas for structured LLM output
    ├── utils.py             # Helper: extract research topic from message history
    └── __init__.py
```

---

## Module Reference

### `app.py` — FastAPI Server
The HTTP layer. Runs on **port 2024** by default.

- Adds CORS middleware (all origins allowed for local dev).
- Mounts the compiled React frontend at `/app` as static files.
- Delegates all research work to `run_research_agent()` from `research_agent.py`.

### `research_agent.py` — Core Research Pipeline
The main async generator that drives every research session. It:

1. **Generates sub-queries** — calls the LLM with `query_writer_instructions` to break the user's question into targeted search queries.
2. **Runs parallel searches** — calls `run_search_pipeline()` (from root `main.py`) for each sub-query, collecting snippets and scraped content from `search_text.md`.
3. **Synthesizes a final answer** — sends all collected content to the LLM with `answer_instructions`.
4. **Saves outputs** — writes `results.txt` (final answer + citations) to the project root.
5. **Yields SSE events** throughout so the frontend can stream progress in real time.

### `graph.py` — LangGraph State Machine
An alternative orchestration path using LangGraph. Defines the same pipeline as a formal state machine with four nodes:

| Node | Role |
|---|---|
| `generate_query` | LLM generates initial search queries |
| `web_research` | Runs one search query through the pipeline |
| `reflection` | LLM identifies knowledge gaps, decides whether to loop |
| `finalize_answer` | LLM produces the final cited answer |

The graph compiles to `graph` (exported as `pro-search-agent`). Edges support conditional branching so research loops back to `web_research` when gaps are found.

### `local_llm.py` — LLM Abstraction Layer
Provides the `LocalLLM` class with a unified `.call()` interface that supports:

- **Local models** via Llama-Swap or Ollama (`/v1/chat/completions` OpenAI-compatible endpoint).
- **Gemini API** via `google-genai` SDK.

**Selection logic at runtime:**
1. If `USE_GEMINI=True` in `.env` → always use Gemini.
2. If the model name contains `"gemini"` → use Gemini directly.
3. Otherwise → try local first, fall back to Gemini if `GEMINI_API_KEY` is set and local fails.

### `state.py` — LangGraph State Schemas
TypedDict classes that define the shape of state flowing through the LangGraph graph:

| Class | Purpose |
|---|---|
| `OverallState` | Full graph state: messages, queries, results, sources, loop counts |
| `ReflectionState` | Output of the reflection node: sufficiency flag, knowledge gap, follow-up queries |
| `QueryGenerationState` | Output of the query generator node |
| `WebSearchState` | Input to each parallel web_research node |

### `configuration.py` — Agent Configuration
A Pydantic `BaseModel` that reads defaults from environment variables:

| Field | Env Var | Default |
|---|---|---|
| `query_generator_model` | `GEMINI_MODEL` | `gemini-2.5-flash-lite` |
| `reflection_model` | `GEMINI_MODEL` | `gemini-2.5-flash-lite` |
| `answer_model` | `GEMINI_MODEL` | `gemini-2.5-flash-lite` |
| `number_of_initial_queries` | — | `3` |
| `max_research_loops` | — | `2` |

### `prompts.py` — LLM Prompt Templates
Four prompt templates used across the pipeline:

| Template | Used By | Purpose |
|---|---|---|
| `query_writer_instructions` | `generate_query` node | Generates diverse sub-queries as structured JSON |
| `web_searcher_instructions` | `web_research` node | Guides per-query synthesis |
| `reflection_instructions` | `reflection` node | Identifies knowledge gaps, outputs JSON `{is_sufficient, knowledge_gap, follow_up_queries}` |
| `answer_instructions` | `finalize_answer` / `research_agent` | Final structured answer with numbered citations only |

### `tools_and_schemas.py` — Pydantic Output Schemas
- `SearchQueryList` — schema for the query generator's structured JSON output.
- `Reflection` — schema for the reflection node's structured JSON output.

---

## API Endpoints

### `POST /chat`
**Primary endpoint for the React frontend.** Accepts a JSON body and streams Server-Sent Events (SSE).

**Request body:**
```json
{
  "messages": [{"type": "human", "content": "Your question", "id": "1"}],
  "initial_search_query_count": 3,
  "max_research_loops": 3,
  "reasoning_model": "gemini-2.5-flash-lite",
  "instructions": "Optional extra context for the agent"
}
```

**SSE event stream** (each line is `data: <json>\n\n`):

| `event` field | When fired | `data` payload |
|---|---|---|
| `generate_query` | Query generation starts / completes | `{"search_query": ["q1", "q2", ...]}` |
| `finalize_answer` | Synthesis begins | `{"status": "Finalizing answer..."}` |
| `complete` | Final answer ready | `{"messages": [...], "sources_gathered": [...], "time_taken": 4.2}` |
| `error` | Any failure | `"Error message string"` |
| `: heartbeat` | Every 5s of idle | *(comment line, no data)* |

A global **45-second timeout** is enforced per request.

---

### `GET /search`
**Simple text endpoint** for CLI and curl usage. Returns plain text with the answer and sources.

**Query parameters:**

| Parameter | Required | Default | Description |
|---|---|---|---|
| `query` | ✅ | — | The search question |
| `effort` | ❌ | `medium` | `low` / `medium` / `high` |
| `model` | ❌ | `$GEMINI_MODEL` | LLM model override |

**Effort → pipeline config mapping:**

| Effort | Initial Queries | Max Loops |
|---|---|---|
| `low` | 1 | 1 |
| `medium` | 3 | 3 |
| `high` | 5 | 10 |

**Example:**
```bash
curl "http://localhost:2024/search?query=Latest+AI+news&effort=high"
```

---

### `GET /health`
Health check. Returns `{"status": "healthy"}`.

---

### `GET /config`
Returns the active LLM configuration read from `.env`:
```json
{
  "use_gemini": false,
  "default_model": "qwen-opus",
  "gemini_model": "gemini-2.5-flash-lite",
  "local_model": "qwen-opus"
}
```

---

### `GET /app/{path}`
Serves the compiled React frontend (static files from `../frontend/dist`). Returns a 503 if the frontend hasn't been built yet.

---

## Environment Variables

All configuration lives in the root `.env` file. The backend loads it via `python-dotenv` on startup.

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Conditional | Required when `USE_GEMINI=True` or as fallback |
| `BRIGHTDATA_API_KEY` | Optional | For BrightData social/video search |
| `TAVILY_API_KEY` | Optional | For Tavily research search |
| `USE_GEMINI` | No | `True` to always use Gemini; `False` for local-first |
| `GEMINI_MODEL` | No | Gemini model name (default: `gemini-2.5-flash-lite`) |
| `LOCAL_MODEL_PORT` | No | Local LLM port (default: `8080` for Llama-Swap, `11434` for Ollama) |
| `LOCAL_MODEL_NAME` | No | Local model name (default: `qwen35-small`) |
| `LOCAL_LLM_TIMEOUT` | No | Timeout in seconds for local LLM requests (default: `180`) |
| `LLAMA_SWAP_BASE_URL` | No | Override full base URL for local LLM (default: `http://127.0.0.1:{LOCAL_MODEL_PORT}`) |

---

## Running the Backend

### With `uv` (recommended)
```bash
cd backend
uv run uvicorn research_engine.app:app --host 0.0.0.0 --port 2024 --reload
```

### With the Makefile
```bash
# From the project root
make dev-backend
```

### With plain Python
```bash
cd backend
pip install -r ../requirements.txt
uvicorn research_engine.app:app --host 0.0.0.0 --port 2024 --reload
```

The server will be available at `http://localhost:2024`.

---

## Output Files

After each research session the backend writes these files to the **project root**:

| File | Content |
|---|---|
| `results.txt` | Final synthesized answer with timestamp, time taken, and numbered source list |
| `search_results.tsv` | Raw search results from all engines (query, engine, rank, title, URL, snippet) |
| `search_text.md` | Full scraped page content used for synthesis (overwritten each run) |

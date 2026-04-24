import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import uuid
import logging
import os
from typing import Literal
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, HttpUrl, field_validator
import io
import os
from fastapi.responses import FileResponse

from orchestrator import ScrapingOrchestrator, ScrapeRequest, ScrapeResponse
from rag_pipeline import RAGPipeline

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Web Scraper API",
    description="Enterprise Playwright + LLM scraping agent",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store (replace with Redis/PostgreSQL in production)
_job_store: dict[str, dict] = {}

orchestrator = ScrapingOrchestrator()
rag_pipeline = RAGPipeline()


# ── Request / Response Models ─────────────────────────────────────────────────

class ScrapePayload(BaseModel):
    url: HttpUrl
    fields: list[str]
    max_pages: int = 5
    export_format: Literal["json", "csv"] = "json"
    llm_provider: Literal["claude", "openai", "gemini"] = "gemini"
    search_query: str = ""        # e.g. "smartwatch" — typed into the site's search bar
    filter_description: str = ""  # e.g. "under 2000 rupees" — applied via UI
    price_filter: str = ""        # Legacy support for what I added earlier by mistake or if user wants it

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, v):
        if not v:
            raise ValueError("At least one field is required")
        if len(v) > 10:
            raise ValueError("Maximum 10 fields per request")
        cleaned = [f.strip() for f in v if f.strip()]
        if not cleaned:
            raise ValueError("Fields cannot be empty strings")
        return cleaned

    @field_validator("max_pages")
    @classmethod
    def validate_pages(cls, v):
        if v < 1 or v > 1000:
            raise ValueError("max_pages must be between 1 and 1000")
        return v


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    result: dict | None = None
    error: str | None = None


class RAGIngestPayload(BaseModel):
    url: HttpUrl
    max_pages: int = 5
    clear_previous: bool = True

class RAGSearchPayload(BaseModel):
    fields: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/scrape", response_model=dict)
async def scrape_sync(payload: ScrapePayload):
    """
    Synchronous scrape endpoint.
    Returns results directly (blocks until complete).
    Use for testing or short scrapes (1-2 pages).
    """
    request = ScrapeRequest(
        url=str(payload.url),
        fields=payload.fields,
        max_pages=payload.max_pages,
        export_format=payload.export_format,
        llm_provider=payload.llm_provider,
        search_query=payload.search_query,
        filter_description=payload.filter_description or payload.price_filter,
    )

    try:
        response: ScrapeResponse = await orchestrator.run(request)
    except Exception as e:
        logger.exception("Unhandled error in /scrape")
        raise HTTPException(status_code=500, detail=str(e))

    if not response.success:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": response.error,
                "validation": response.validation,
                "fields_searched": response.fields_searched,
            }
        )

    return {
        "success": True,
        "data": response.data,
        "validation": response.validation,
        "fields_searched": response.fields_searched,
        "total_pages_scraped": response.total_pages_scraped,
        "export_csv": response.export_csv if payload.export_format == "csv" else None,
    }


@app.post("/scrape/async", response_model=JobStatusResponse)
async def scrape_async(payload: ScrapePayload, background_tasks: BackgroundTasks):
    """
    Async scrape endpoint — returns job_id immediately.
    Client polls /jobs/{job_id} for status + results.
    In production: replace background_tasks with Celery.
    """
    job_id = str(uuid.uuid4())
    _job_store[job_id] = {"status": "queued", "result": None, "error": None}

    async def _run_job():
        _job_store[job_id]["status"] = "running"
        try:
            request = ScrapeRequest(
                url=str(payload.url),
                fields=payload.fields,
                max_pages=payload.max_pages,
                export_format=payload.export_format,
                llm_provider=payload.llm_provider,
            )
            response = await orchestrator.run(request)
            _job_store[job_id]["status"] = "completed" if response.success else "failed"
            _job_store[job_id]["result"] = {
                "success": response.success,
                "data": response.data,
                "validation": response.validation,
                "total_pages_scraped": response.total_pages_scraped,
                "fields_searched": response.fields_searched,
            }
            if not response.success:
                _job_store[job_id]["error"] = response.error
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            _job_store[job_id]["status"] = "failed"
            _job_store[job_id]["error"] = str(e)

    background_tasks.add_task(_run_job)
    return JobStatusResponse(job_id=job_id, status="queued")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        result=job.get("result"),
        error=job.get("error"),
    )


@app.get("/jobs/{job_id}/export")
async def export_job(job_id: str, format: Literal["json", "csv"] = "json"):
    """Download job results as JSON or CSV."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Job not completed yet: {job['status']}")

    data = job["result"]["data"]

    if format == "json":
        content = __import__("json").dumps(data, indent=2)
        return StreamingResponse(
            io.StringIO(content),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=scrape_{job_id}.json"}
        )
    else:
        import csv as csv_mod
        keys = sorted({k for item in data for k in item.keys() if not k.startswith("_")})
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=scrape_{job_id}.csv"}
        )

# ── RAG Endpoints ─────────────────────────────────────────────────────────────

@app.post("/rag/ingest")
async def rag_ingest(payload: RAGIngestPayload):
    """
    Scrape a website and store its text in a local ChromaDB collection.
    NO LLM API USED.
    """
    if payload.clear_previous:
        rag_pipeline.clear_collection()
        
    total_chunks = await rag_pipeline.ingest_url(str(payload.url), payload.max_pages)
    return {"success": True, "message": f"Successfully ingested {total_chunks} chunks from {payload.url}"}

@app.post("/rag/clear")
async def rag_clear():
    """
    Clear the local ChromaDB collection (starts a fresh session).
    """
    rag_pipeline.clear_collection()
    return {"success": True, "message": "Memory cleared for a new session"}

@app.post("/rag/search")
async def rag_search(payload: RAGSearchPayload):
    """
    Search the local ChromaDB collection using key fields, and extract using LLM.
    USES ONLY 1 LLM API CALL!
    """
    try:
        import asyncio
        data = await asyncio.to_thread(rag_pipeline.retrieve_and_extract, payload.fields)
        return {"success": True, "data": data}
    except Exception as e:
        logger.exception("RAG Search Error")
        raise HTTPException(status_code=500, detail=str(e))


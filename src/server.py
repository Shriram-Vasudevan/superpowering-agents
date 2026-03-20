"""FastAPI HTTP server exposing the superpower pipeline as a service."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.models import (
    ContextRequest,
    GenerateRequest,
    GenerateResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from src.pipeline import (
    build_context_system_prompt,
    build_context_payload,
    intent_to_info,
    result_to_reference_item,
    run_retrieval,
    search_images,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load index and embeddings on startup."""
    from src.retrieval import load_index

    load_index()
    yield


app = FastAPI(
    title="Superpowering Agents",
    description="Design-reference-backed context injection for LLM code generation",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_endpoint(req: RetrieveRequest):
    intent, results = run_retrieval(
        req.prompt,
        page_type=req.page_type,
        industry=req.industry,
        top_k=req.top_k,
        no_vector=req.no_vector,
    )
    return RetrieveResponse(
        intent=intent_to_info(intent),
        references=[result_to_reference_item(r) for r in results],
    )


@app.post("/generate", response_model=GenerateResponse)
async def generate_endpoint(req: GenerateRequest):
    from src.generation import generate_code

    intent, results = run_retrieval(
        req.prompt,
        page_type=req.page_type,
        industry=req.industry,
        top_k=req.top_k,
        no_vector=req.no_vector,
    )
    compiled_system_prompt, _ = build_context_system_prompt(req.prompt, intent, results)
    code = generate_code(req.prompt, results, system_prompt=compiled_system_prompt)
    return GenerateResponse(
        intent=intent_to_info(intent),
        code=code,
        references=[result_to_reference_item(r) for r in results],
    )


@app.post("/context")
async def context_endpoint(req: ContextRequest):
    intent, results = run_retrieval(
        req.prompt,
        page_type=req.page_type,
        industry=req.industry,
        top_k=req.top_k,
        no_vector=req.no_vector,
    )
    return build_context_payload(req.prompt, intent, results)


@app.get("/images")
async def images_endpoint(query: str, count: int = 8, orientation: str | None = None):
    return {"images": search_images(query, count=count, orientation=orientation)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=True)

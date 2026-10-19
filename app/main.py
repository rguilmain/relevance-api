"""FastAPI application factory and routes.

Run with::

    uv run uvicorn app.main:create_app --factory
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.models import (
    BatchRequest,
    ByDocResponse,
    ByQueryResponse,
    DocLookupIn,
    DocScore,
    InteractionIn,
    InteractionResult,
    QueryLookupIn,
    QueryScore,
    format_validation_error,
)
from app.repository import Repository


def _check_batch_size(count: int, max_batch_size: int) -> None:
    if count < 1 or count > max_batch_size:
        raise HTTPException(
            status_code=422,
            detail=f"items must contain between 1 and {max_batch_size} entries",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    ``settings`` defaults to ``Settings.from_env()``; passing one in lets
    tests point the app at a temporary database.
    """
    if settings is None:
        settings = Settings.from_env()

    repository = Repository(settings.db_path)
    repository.init_schema()

    app = FastAPI(title="relevance-api")

    def _record(item: InteractionIn) -> InteractionResult:
        examined = repository.record_interaction(
            item.index_id, item.query, item.doc_ids, item.clicked_doc_id
        )
        return InteractionResult(
            index_id=item.index_id, query=item.query, docs_examined=examined
        )

    def _by_query(item: QueryLookupIn) -> ByQueryResponse:
        cutoff = (
            item.min_examines
            if item.min_examines is not None
            else settings.min_examines
        )
        rows = repository.lookup_by_query(item.index_id, item.query, cutoff)
        return ByQueryResponse(
            index_id=item.index_id,
            query=item.query,
            docs=[
                DocScore(doc_id=doc_id, relevance=successes / examines)
                for doc_id, successes, examines in rows
            ],
        )

    def _by_doc(item: DocLookupIn) -> ByDocResponse:
        cutoff = (
            item.min_examines
            if item.min_examines is not None
            else settings.min_examines
        )
        rows = repository.lookup_by_doc(item.index_id, item.doc_id, cutoff)
        return ByDocResponse(
            index_id=item.index_id,
            doc_id=item.doc_id,
            queries=[
                QueryScore(query=query, relevance=successes / examines)
                for query, successes, examines in rows
            ],
        )

    def _run_batch(
        items: list[Any],
        model: type[BaseModel],
        handler: Callable[[Any], BaseModel],
    ) -> dict[str, Any]:
        _check_batch_size(len(items), settings.max_batch_size)
        results: list[dict[str, Any]] = []
        for position, raw in enumerate(items):
            try:
                item = model.model_validate(raw)
            except ValidationError as exc:
                results.append(
                    {
                        "position": position,
                        "ok": False,
                        "error": format_validation_error(exc),
                    }
                )
                continue
            # Each valid item is applied in order, in its own transaction.
            results.append(
                {
                    "position": position,
                    "ok": True,
                    "result": handler(item).model_dump(),
                }
            )
        return {"results": results}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/interactions", response_model=InteractionResult)
    def create_interaction(body: InteractionIn) -> InteractionResult:
        return _record(body)

    @app.post("/v1/interactions/batch")
    def create_interactions_batch(body: BatchRequest) -> dict[str, Any]:
        return _run_batch(body.items, InteractionIn, _record)

    @app.post("/v1/relevance/by-query", response_model=ByQueryResponse)
    def relevance_by_query(body: QueryLookupIn) -> ByQueryResponse:
        return _by_query(body)

    @app.post("/v1/relevance/by-doc", response_model=ByDocResponse)
    def relevance_by_doc(body: DocLookupIn) -> ByDocResponse:
        return _by_doc(body)

    @app.post("/v1/relevance/by-query/batch")
    def relevance_by_query_batch(body: BatchRequest) -> dict[str, Any]:
        return _run_batch(body.items, QueryLookupIn, _by_query)

    @app.post("/v1/relevance/by-doc/batch")
    def relevance_by_doc_batch(body: BatchRequest) -> dict[str, Any]:
        return _run_batch(body.items, DocLookupIn, _by_doc)

    return app

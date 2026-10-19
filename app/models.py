"""Pydantic request/response models.

``index_id``, ``doc_id`` and ``clicked_doc_id`` are strict strings (no
coercion) of 1-512 characters, stored exactly as given. ``query`` is
normalized inside a validator, so all downstream code only ever sees the
normalized form.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.normalize import normalize_query

MAX_ID_LENGTH = 512
MAX_QUERY_LENGTH = 512

IdStr = Annotated[StrictStr, Field(min_length=1, max_length=MAX_ID_LENGTH)]
#: ``2**63 - 1`` is the largest SQLite INTEGER; a bigger cutoff could never
#: match a stored ``num_examines``.
MinExamines = Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]


def _normalize_and_validate(query: str) -> str:
    normalized = normalize_query(query)
    if not normalized:
        raise PydanticCustomError(
            "query_empty", "query must not be empty after normalization"
        )
    if len(normalized) > MAX_QUERY_LENGTH:
        raise PydanticCustomError(
            "query_too_long",
            "query must be at most 512 characters after normalization",
        )
    return normalized


NormalizedQuery = Annotated[StrictStr, AfterValidator(_normalize_and_validate)]


class InteractionIn(BaseModel):
    """One interaction: docs shown (in order) and the doc that was clicked."""

    model_config = ConfigDict(extra="forbid")

    index_id: IdStr
    query: NormalizedQuery
    doc_ids: Annotated[list[IdStr], Field(min_length=1)]
    clicked_doc_id: IdStr

    @field_validator("doc_ids")
    @classmethod
    def _no_duplicate_doc_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise PydanticCustomError(
                "duplicate_doc_ids", "doc_ids must not contain duplicates"
            )
        return value

    @field_validator("clicked_doc_id")
    @classmethod
    def _clicked_doc_id_must_be_in_doc_ids(cls, value: str, info) -> str:
        doc_ids = info.data.get("doc_ids")
        # doc_ids is declared before clicked_doc_id, so it is usually present;
        # if it failed validation it is absent and this check is skipped.
        if doc_ids is None:
            return value
        if value not in doc_ids:
            raise PydanticCustomError(
                "clicked_doc_id_not_in_doc_ids",
                "clicked_doc_id must be in doc_ids",
            )
        return value


class QueryLookupIn(BaseModel):
    """Lookup relevance per doc for one (index_id, query)."""

    model_config = ConfigDict(extra="forbid")

    index_id: IdStr
    query: NormalizedQuery
    min_examines: MinExamines | None = None


class DocLookupIn(BaseModel):
    """Lookup relevance per query for one (index_id, doc_id)."""

    model_config = ConfigDict(extra="forbid")

    index_id: IdStr
    doc_id: IdStr
    min_examines: MinExamines | None = None


class InteractionResult(BaseModel):
    index_id: str
    query: str
    docs_examined: int


class DocScore(BaseModel):
    doc_id: str
    relevance: float


class QueryScore(BaseModel):
    query: str
    relevance: float


class ByQueryResponse(BaseModel):
    index_id: str
    query: str
    docs: list[DocScore]


class ByDocResponse(BaseModel):
    index_id: str
    doc_id: str
    queries: list[QueryScore]


class BatchRequest(BaseModel):
    """Envelope for every batch endpoint.

    ``items`` is deliberately ``list[Any]``: each item is validated
    individually with ``Model.model_validate`` so that one bad item does not
    reject the whole batch.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[Any]


def format_validation_error(exc: ValidationError) -> str:
    """Render a ``ValidationError`` as ``"loc: msg; loc: msg"``."""
    return "; ".join(
        f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
        for error in exc.errors()
    )

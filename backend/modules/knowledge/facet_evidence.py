"""Request-local proof references for cases with two selected evidence passages."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FacetEvidenceRef:
    document_id: str
    document_version: str
    edition_version: str
    section_id: str
    page: int
    text_sha256: str

    @classmethod
    def from_hit(cls, hit: dict[str, Any]) -> FacetEvidenceRef | None:
        binding = tuple(hit.get(name) for name in ("document_id", "document_version", "edition_version", "section_id"))
        page, body = hit.get("page"), hit.get("text")
        if (not all(isinstance(value, str) and value for value in binding) or type(page) is not int or page <= 0
                or not isinstance(body, str) or not body or hit.get("partial_readonly_table") or hit.get("source_range_reduced")):
            return None
        return cls(*binding, page, _digest(body))


@dataclass(frozen=True)
class FacetEvidence:
    query_sha256: str
    kind: str
    references: tuple[FacetEvidenceRef, FacetEvidenceRef]

    @classmethod
    def capture(cls, edition, query: str, kind: str, pair: tuple[dict[str, Any], dict[str, Any]]) -> FacetEvidence | None:
        from .edition import _page_texts, _source_excerpt
        from .reader import DocumentReadError

        references = tuple(FacetEvidenceRef.from_hit(hit) for hit in pair)
        first, second = references
        if first is None or second is None or first == second:
            return None
        verified = {}
        for ref, hit in zip((first, second), pair, strict=True):
            if ref.edition_version != edition.version:
                return None
            key = ref.document_id, ref.document_version
            if key not in verified:
                try:
                    reading = edition.read(*key, include_original_status=False)
                    verified[key] = _page_texts(reading)
                except (DocumentReadError, OSError, KeyError, ValueError):
                    return None
            page = verified[key].get(ref.page)
            if not page or page[0] != ref.section_id or not _source_excerpt(hit["text"], page[1]):
                return None
        return cls(_digest(query), kind, (first, second))

    def select_hits(self, query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Return both unchanged hits in retrieval order when the selection still binds."""
        if self.query_sha256 != _digest(query):
            return None
        requested = set(self.references)
        selected = [hit for hit in hits if FacetEvidenceRef.from_hit(hit) in requested]
        return selected if len(selected) == 2 and {FacetEvidenceRef.from_hit(hit) for hit in selected} == requested else None

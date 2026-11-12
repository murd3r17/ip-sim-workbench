"""Resume an exact bundled corpus import into a dedicated local AnythingLLM workspace."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from scripts.full_lifecycle import checkpoint, operation_lock, receipt_path  # noqa: E402
from scripts.full_preflight import load_config  # noqa: E402
from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider, _first_list  # noqa: E402
from modules.knowledge.reader import MAX_SOURCE_BYTES  # noqa: E402

QUERIES = ("OSPF 邻居建立 Full", "BGP 路由选择", "MPLS LDP 标签分发")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_path(path: Path, boundary: Path) -> Path:
    require(path.is_relative_to(boundary), "source_path_outside_boundary")
    for item in (path, *path.parents):
        if item == boundary.parent:
            break
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(), "source_link_forbidden")
    return path


def load_manifest(stage: Path, corpus: Path, expected: int = 135) -> tuple[str, list[tuple[dict, bytes]]]:
    manifest = safe_path(stage / "corpus-manifest.json", stage)
    rows = json.loads(manifest.read_bytes())["documents"]
    require(len(rows) == expected and len({row["source"] for row in rows}) == expected, "corpus_count_mismatch")
    result = []
    for index, row in enumerate(rows, 1):
        require(row["file"] == f"doc-{index:03}.md", "invalid_corpus_filename")
        source = PurePosixPath(row["source"])
        require(not source.is_absolute() and ".." not in source.parts and "\\" not in str(source), "invalid_corpus_source")
        source_path = safe_path(corpus.joinpath(*source.parts), corpus)
        staged = safe_path(stage / row["file"], stage)
        require(0 < staged.stat().st_size <= MAX_SOURCE_BYTES and source_path.stat().st_size == staged.stat().st_size,
                "invalid_corpus_size")
        content = staged.read_bytes()
        require(digest(content) == row["sha256"] and source_path.read_bytes() == content, "corpus_source_changed")
        result.append((row, content))
    return digest(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()), result


def load_metadata(path: Path, directory: Path) -> dict:
    safe_path(path, directory)
    require(0 < path.stat().st_size <= MAX_SOURCE_BYTES, "provider_metadata_size")
    return json.loads(path.read_bytes())


def local_metadata(directory: Path, names: set[str]) -> dict[str, tuple[Path, dict]]:
    result = {}
    for path in sorted(directory.glob("*.json")):
        # All managed filenames carry the namespace of this corpus and workspace.
        if not any(path.name.startswith(name + "-") for name in names):
            continue
        metadata = load_metadata(path, directory)
        name = metadata.get("title")
        require(name in names and name not in result, "duplicate_or_unexpected_provider_document")
        result[name] = (path, metadata)
    return result


def persist_source(path: Path, metadata: dict, uploads: Path, name: str, content: bytes) -> str:
    source = safe_path(uploads / name, uploads)
    if not source.exists():
        tmp = uploads / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp, source)
            except FileExistsError:
                pass
        finally:
            tmp.unlink(missing_ok=True)
    require(source.stat().st_size == len(content) and source.read_bytes() == content, "persistent_source_content_conflict")
    if metadata.get("url") != source.as_uri():
        checkpoint(path, {**metadata, "url": source.as_uri()})
    return f"custom-documents/{path.name}"


async def sync(provider, stage: Path, storage: Path, corpus: Path, *, apply: bool, expected: int = 135) -> dict:
    version, rows = load_manifest(stage, corpus, expected)
    workspace = await provider.get_workspace()
    slug = provider.workspace_slug
    require(workspace.get("slug") == slug and workspace.get("id") not in (None, "", slug), "provider_workspace_not_verified")
    binding = {"workspace": slug, "workspace_id": str(workspace["id"]), "corpus_sha256": version,
               "endpoint_sha256": digest(provider.base_url.encode()), "storage_sha256": digest(str(storage).encode())}
    namespace = digest(json.dumps(binding, sort_keys=True).encode())[:16]
    names = {f"ipsim-{namespace}-{index:03}.md": item for index, item in enumerate(rows, 1)}
    directory = safe_path(storage / "documents/custom-documents", storage)
    uploads = safe_path(storage / "documents/uploads", storage)
    state_path = safe_path(stage / "knowledge-sync.json", stage)
    previous = json.loads(state_path.read_bytes()) if state_path.exists() else None
    require(previous is None or previous.get("binding") == binding, "sync_receipt_target_or_corpus_changed")
    docs = [provider._normalize_document(item) for item in _first_list(workspace, ("documents",))]
    members = {item["title"]: item for item in docs}
    require(len(members) == len(docs) and set(members) <= set(names), "workspace_not_empty_or_already_used")
    state = {"schema": 1, "binding": binding, "expected_documents": expected,
             "verified": {}, "status": "IN_PROGRESS", "search": []}
    if apply:
        checkpoint(state_path, state)
    try:
        stored = local_metadata(directory, set(names))
        if apply:
            uploads.mkdir(parents=True, exist_ok=True)
        for name, (row, content) in names.items():
            if name not in stored and apply:
                response = await provider._request("POST", "/api/v1/document/upload",
                                                   files={"file": (name, content, "text/markdown")})
                uploaded = _first_list(response, ("documents",))
                require(len(uploaded) == 1 and response.get("success") is not False, "provider_upload_incomplete")
                ref = PurePosixPath(str(uploaded[0].get("location", "")))
                require(len(ref.parts) == 2 and ref.parts[0] == "custom-documents"
                        and ref.name.startswith(name + "-") and ref.suffix == ".json", "provider_upload_location_unverified")
                path = directory / ref.name
                metadata = load_metadata(path, directory)
                require(metadata.get("title") == name, "provider_upload_metadata_unverified")
                stored[name] = path, metadata
            require(name in stored, "provider_document_missing")
            path, metadata = stored[name]
            docpath = f"custom-documents/{path.name}"
            state["current"] = row["file"]
            if name in members:
                require(members[name]["id"] == docpath, "workspace_document_identity_conflict")
            if apply:
                persist_source(path, metadata, uploads, name, content)
                if name not in members:
                    checkpoint(state_path, state)
                    response = await provider._request("POST", f"/api/v1/workspace/{slug}/update-embeddings",
                                                       json={"adds": [docpath], "deletes": []})
                    require(isinstance(response, dict) and response.get("success") is not False, "provider_embedding_failed")
            state["verified"][row["file"]] = {"id": docpath, "sha256": row["sha256"]}
        docs = await provider.list_documents()
        final = {item["title"]: item for item in docs}
        require(len(docs) == expected and set(final) == set(names), "workspace_membership_incomplete")
        for name, (row, _) in names.items():
            doc = final[name]
            require(doc["id"] == state["verified"][row["file"]]["id"], "workspace_document_identity_conflict")
            source = await provider.read_document(None, doc)
            require(source["version"] == row["sha256"] and source["content"].strip(), "persistent_source_hash_mismatch")
        for query in QUERIES:
            sources = await provider.search(query, top_k=8)
            found = [item for item in sources if item.get("text", "").strip()
                     and (item.get("title") in final or item.get("title") in {doc["id"] for doc in docs})]
            require(bool(found), "workspace_vector_search_unverified")
            state["search"].append({"query": query, "source_count": len(found)})
        state.update(status="VERIFIED", document_count=expected)
        state.pop("current", None)
    except BaseException:
        state["status"] = "INCOMPLETE"
        raise
    finally:
        if apply:
            checkpoint(state_path, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--confirm-workspace", required=True)
    parser.add_argument("--apply", action="store_true", help="Upload and embed into the confirmed workspace. Default only verifies.")
    args = parser.parse_args()
    try:
        stage = receipt_path(ROOT, args.corpus_dir.absolute() / "corpus-manifest.json", 8000).parent
        storage = args.storage.absolute()
        safe_path(storage, storage)
        require(stage.is_dir() and storage.is_dir(), "missing_corpus_or_storage_directory")
        config = load_config(ROOT)
        slug = config["KNOWLEDGE_WORKSPACE_SLUG"]
        endpoint = urlsplit(config["KNOWLEDGE_BASE_URL"])
        require(config["KNOWLEDGE_PROVIDER"] == "anythingllm" and args.confirm_workspace == slug
                and bool(re.fullmatch(r"[a-zA-Z0-9_-]+", slug)), "workspace_confirmation_mismatch")
        require(endpoint.scheme in {"http", "https"} and endpoint.hostname
                and not (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment)
                and (endpoint.hostname == "localhost" or ipaddress.ip_address(endpoint.hostname).is_loopback),
                "dedicated_local_knowledge_endpoint_required")
        require(bool(config["KNOWLEDGE_API_KEY"]), "knowledge_api_key_missing")
        # The same reader used by the workbench verifies persistent bytes and
        # membership. Redirects stay disabled for the operator's API key.
        os.environ["KNOWLEDGE_ANYTHINGLLM_STORAGE"] = str(storage)
        import httpx

        async def run():
            provider = AnythingLLMKnowledgeProvider(config["KNOWLEDGE_BASE_URL"], config["KNOWLEDGE_API_KEY"], slug)
            async with httpx.AsyncClient(timeout=120, trust_env=False, follow_redirects=False) as client:
                provider._client = client
                return await sync(provider, stage, storage, ROOT / "knowledge/corpus/huawei-ip", apply=args.apply)

        with operation_lock(stage):
            result = asyncio.run(run())
        print(json.dumps({"status": result["status"], "document_count": result["document_count"],
                          "corpus_sha256": result["binding"]["corpus_sha256"], "search": result["search"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        reason = str(exc) if type(exc) is ValueError and re.fullmatch(r"[a-z_]+", str(exc)) else type(exc).__name__
        print(json.dumps({"status": "INCOMPLETE", "reason": reason}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

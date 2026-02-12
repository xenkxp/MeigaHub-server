from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable

import httpx

from .config import settings


def ensure_models_dir() -> Path:
    models_path = Path(settings.models_dir)
    models_path.mkdir(parents=True, exist_ok=True)
    return models_path


def list_local_models() -> list[str]:
    models_path = ensure_models_dir()
    return sorted([p.name for p in models_path.glob("*.gguf") if p.is_file()])


def list_local_models_with_sizes() -> list[dict]:
    models_path = ensure_models_dir()
    items = []
    for p in models_path.glob("*.gguf"):
        if p.is_file():
            items.append({"name": p.name, "size": p.stat().st_size})
    return sorted(items, key=lambda x: x["name"].lower())


def delete_local_model(filename: str) -> None:
    models_path = ensure_models_dir()
    safe_name = safe_filename(filename)
    target = models_path / safe_name
    if not target.exists():
        raise FileNotFoundError("modelo no encontrado")
    target.unlink()


def safe_filename(name: str) -> str:
    filename = os.path.basename(name)
    if not filename.lower().endswith(".gguf"):
        raise ValueError("solo se permiten archivos .gguf")
    if filename in {".", ".."}:
        raise ValueError("nombre inválido")
    return filename


def download_file(
    url: str,
    filename: str,
    token: str | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> Path:
    models_path = ensure_models_dir()
    safe_name = safe_filename(filename)
    destination = models_path / safe_name

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(follow_redirects=True, timeout=None) as client:
        with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            total = response.headers.get("content-length")
            total_bytes = int(total) if total and total.isdigit() else None
            downloaded = 0
            with destination.open("wb") as f:
                for chunk in response.iter_bytes():
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total_bytes)
    return destination


def hf_search_models(query: str, limit: int = 10, tag_filter: str | None = None) -> list[dict]:
    url = "https://huggingface.co/api/models"
    params: dict[str, str] = {"search": query, "limit": str(limit)}
    if tag_filter:
        params["filter"] = tag_filter
    headers = {}
    if settings.huggingface_token:
        headers["Authorization"] = f"Bearer {settings.huggingface_token}"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _has_gguf_hint(item: dict) -> bool:
    """Quick check: does the HF search result already hint at GGUF?"""
    tags = item.get("tags") or []
    if any(t.lower() == "gguf" for t in tags):
        return True
    repo = (item.get("modelId") or item.get("id") or "").lower()
    return "gguf" in repo


def hf_search_models_with_flags(
    query: str,
    limit: int = 10,
    only_gguf: bool = False,
) -> list[dict]:
    """Search HF and annotate each result with has_gguf / gguf_count."""
    tag = "gguf" if only_gguf else None
    raw = hf_search_models(query, limit, tag_filter=tag)
    results: list[dict] = []
    verified = 0
    max_verify = 12          # API calls budget
    for item in raw:
        repo = item.get("modelId") or item.get("id")
        if not repo:
            results.append(item)
            continue

        item = dict(item)     # shallow copy

        # ---- fast path: tags / repo name already tell us ----
        if _has_gguf_hint(item):
            # likely GGUF — try to get exact count if budget left
            if verified < max_verify:
                try:
                    files = hf_list_files(repo)
                    item["has_gguf"] = bool(files)
                    item["gguf_count"] = len(files)
                except Exception:
                    item["has_gguf"] = True   # trust the hint
                    item["gguf_count"] = None
                verified += 1
            else:
                item["has_gguf"] = True
                item["gguf_count"] = None
        else:
            # no hint — verify via API if budget left
            if verified < max_verify:
                try:
                    files = hf_list_files(repo)
                    item["has_gguf"] = bool(files)
                    item["gguf_count"] = len(files)
                except Exception:
                    item["has_gguf"] = None
                    item["gguf_count"] = None
                verified += 1
            else:
                item["has_gguf"] = None
                item["gguf_count"] = None

        results.append(item)
    return results


def hf_list_files(repo: str) -> list[str]:
    url = f"https://huggingface.co/api/models/{repo}"
    headers = {}
    if settings.huggingface_token:
        headers["Authorization"] = f"Bearer {settings.huggingface_token}"
    with httpx.Client(timeout=8.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    siblings: Iterable[dict] = data.get("siblings", [])
    files = [item.get("rfilename", "") for item in siblings]
    return sorted([name for name in files if name.lower().endswith(".gguf")])


def hf_list_files_with_sizes(repo: str) -> list[dict]:
    """List GGUF files with sizes using HF tree API (always returns sizes)."""
    headers = {}
    if settings.huggingface_token:
        headers["Authorization"] = f"Bearer {settings.huggingface_token}"

    # Intentar la API de tree primero (siempre devuelve size)
    items: list[dict] = []
    try:
        tree_url = f"https://huggingface.co/api/models/{repo}/tree/main"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(tree_url, headers=headers)
            response.raise_for_status()
            data = response.json()
        for entry in data:
            path = entry.get("path", "")
            if path.lower().endswith(".gguf"):
                items.append({"name": path, "size": entry.get("size")})
    except Exception:
        # Fallback: API de modelo (siblings, a veces sin size)
        model_url = f"https://huggingface.co/api/models/{repo}"
        with httpx.Client(timeout=10.0) as client:
            response = client.get(model_url, headers=headers)
            response.raise_for_status()
            data = response.json()
        siblings: Iterable[dict] = data.get("siblings", [])
        for item in siblings:
            name = item.get("rfilename", "")
            if name.lower().endswith(".gguf"):
                items.append({"name": name, "size": item.get("size")})

    return sorted(items, key=lambda x: x["name"].lower())


def hf_resolve_url(repo: str, filename: str) -> str:
    safe_name = safe_filename(filename)
    return f"https://huggingface.co/{repo}/resolve/main/{safe_name}"

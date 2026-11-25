"""Read one permitted page from an administrator-mounted textbook original."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from threading import Lock

import pymupdf

from .reader import DocumentReadError


_render_lock = Lock()


def _fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=32)
def _matches(path: Path, fingerprint: tuple[int, ...], digest: str) -> bool:
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    return actual == digest and _fingerprint(path) == fingerprint


class OriginalPdfLibrary:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()

    def _path(self, book: dict) -> Path:
        filename = book.get("filename")
        if not isinstance(filename, str) or not filename:
            raise DocumentReadError("original_invalid", "该书册缺少原版 PDF 文件名登记。请核对冻结教材的 manifest.json。", 409)
        name = Path(filename)
        if name.name != str(name) or name.suffix.lower() != ".pdf":
            raise DocumentReadError("original_invalid", "原件登记无效，请联系管理员。")
        path = (self.directory / name).resolve()
        if not path.is_relative_to(self.directory) or not path.is_file():
            raise DocumentReadError("original_not_mounted", "尚未挂载这本书的原版 PDF。", 404)
        return path

    def page_status(self, book: dict) -> str:
        try:
            path = self._path(book)
            if _matches(path, _fingerprint(path), book["sha256"]):
                return "available"
        except DocumentReadError as exc:
            return exc.code
        except OSError:
            return "original_unavailable"
        return "original_version_mismatch"

    def render(self, book: dict, number: int) -> bytes:
        try:
            path = self._path(book)
            with _render_lock:
                fingerprint = _fingerprint(path)
                if not _matches(path, fingerprint, book["sha256"]):
                    raise DocumentReadError("original_version_mismatch", "挂载的 PDF 与登记版本不同，请联系管理员。", 409)
                with pymupdf.open(path) as pdf:
                    if pdf.page_count != book["pages"] or not 1 <= number <= pdf.page_count:
                        raise DocumentReadError("original_page_unavailable", "原件页数与登记不符，请联系管理员。", 409)
                    page = pdf[number - 1]
                    scale = min(3.0, 2400 / max(page.rect.width, page.rect.height))
                    image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
                if _fingerprint(path) != fingerprint:
                    raise DocumentReadError("original_version_mismatch", "PDF 在读取期间发生变化，请重新打开。", 409)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DocumentReadError("original_unavailable", "原件读取失败，请联系管理员核对 PDF。") from exc
        return image

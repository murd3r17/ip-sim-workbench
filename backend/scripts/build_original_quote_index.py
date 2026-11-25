"""Build the local quoted-text lookup index for a frozen and mounted edition."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import NamedTemporaryFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.knowledge.edition import open_edition
from modules.knowledge.original_index import INDEX_NAME, SCANS_INDEX_NAME, _normalized, build_original_index
from modules.knowledge.reader import DocumentReadError


def local_scan_reader():
    """Return a local recognizer. Do not add weak matches or expose recognized text."""
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise SystemExit("扫描索引需要可选依赖。请在当前后端虚拟环境安装 rapidocr_onnxruntime 和 opencv-python-headless 后重试。") from exc

    cv2.setNumThreads(1)
    recognize = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1, use_cls=False)

    def scan(page):
        import pymupdf

        scale = min(2.4, 1600 / max(page.rect.width, page.rect.height))
        image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        rows, _ = recognize(image.tobytes("png"))
        return "\n".join(_normalized(row[1]) if row[2] >= .86 else "^" for row in rows or [])

    return scan


def build(edition_dir: Path, originals: Path, *, scans: bool) -> dict:
    paths = (("--edition", edition_dir.expanduser()), ("--originals", originals.expanduser()))
    for flag, path in paths:
        if not path.is_dir():
            raise ValueError(f"找不到 {flag} 指定的目录 {path}。请检查目录路径。")
    root = paths[0][1].resolve()
    edition = open_edition(str(root), str(paths[1][1].resolve()))
    scan_reader = local_scan_reader() if scans else None
    target = root / (SCANS_INDEX_NAME if scans else INDEX_NAME)
    skipped = []
    if scans:
        source = root / ".original-scans-checkpoint.sqlite3"
        with closing(sqlite3.connect(root / ".original-scans-builder-lock.sqlite3", timeout=0)) as lock:
            try:
                lock.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                raise ValueError("无法锁定扫描索引目录，请确认没有其他扫描任务正在使用它。") from exc

            def progress(book, checked, total, indexed):
                print(f"Book {book:02}: checked {checked}/{total} approved pages, {indexed} scan locators", file=sys.stderr, flush=True)

            report = build_original_index(edition, source, read_scan=scan_reader, skipped=skipped,
                                          scan_checkpoint=True, progress=progress)
            os.replace(source, target)
    else:
        with NamedTemporaryFile(dir=root, prefix=".original-quotes-", suffix=".sqlite3", delete=False) as staging:
            source = Path(staging.name)
        try:
            report = build_original_index(edition, source, skipped=skipped)
            os.replace(source, target)
        finally:
            source.unlink(missing_ok=True)
    return {**report, "scan_errors": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="为冻结教材挂载的原书 PDF 建立本机原句索引。")
    parser.add_argument("--edition", type=Path, required=True, help="冻结教材目录")
    parser.add_argument("--originals", type=Path, required=True, help="已登记原版 PDF 所在目录")
    parser.add_argument("--scans", action="store_true", help="使用可选的本地 OCR 建立扫描定位索引")
    args = parser.parse_args()
    try:
        report = build(args.edition, args.originals, scans=args.scans)
    except DocumentReadError as exc:
        parser.exit(2, f"索引未生成。{exc.message}\n")
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        parser.exit(2, f"索引未生成。请核对冻结教材清单、原书登记及目录权限。{exc}\n")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()

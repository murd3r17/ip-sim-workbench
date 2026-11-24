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


def local_scan_reader():
    """Return a local recognizer. Do not add weak matches or expose recognized text."""
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise SystemExit("Scan indexing requires the optional local RapidOCR packages.") from exc

    cv2.setNumThreads(1)
    recognize = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1, use_cls=False)

    def scan(page):
        import pymupdf

        scale = min(2.4, 1600 / max(page.rect.width, page.rect.height))
        image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        rows, _ = recognize(image.tobytes("png"))
        return "\n".join(_normalized(row[1]) if row[2] >= .86 else "^" for row in rows or [])

    return scan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--scans", action="store_true", help="Build separate tentative scan locators using local OCR.")
    args = parser.parse_args()
    root = args.edition.resolve(strict=True)
    edition = open_edition(str(root), str(args.originals.resolve(strict=True)))
    target = root / (SCANS_INDEX_NAME if args.scans else INDEX_NAME)
    skipped = []
    if args.scans:
        source = root / ".original-scans-checkpoint.sqlite3"
        with closing(sqlite3.connect(root / ".original-scans-builder-lock.sqlite3", timeout=0)) as lock:
            try:
                lock.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                raise SystemExit("Cannot acquire the scan-index build lock. Check for a running scan or a locked directory.") from exc

            def progress(book, checked, total, indexed):
                print(f"Book {book:02}: checked {checked}/{total} approved pages, {indexed} scan locators", file=sys.stderr, flush=True)

            report = build_original_index(edition, source, read_scan=local_scan_reader(), skipped=skipped,
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
    print(json.dumps({**report, "scan_errors": skipped}, ensure_ascii=True))


if __name__ == "__main__":
    main()

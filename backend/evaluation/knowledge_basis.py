"""Verify the manually curated basis against raw files, without fuzzy fallback."""
import hashlib
from pathlib import Path


def verify(review, questions, root):
    root = Path(root).resolve()
    expected = {f"{q['id']}-F{i:02d}": (q["id"], text)
                for q in questions for i, text in enumerate(q["facts"], 1)}
    errors, seen = [], set()
    for fact in review["facts"]:
        fid = fact["id"]
        if fid in seen or expected.get(fid) != (fact["question_id"], fact["original_fact"]):
            errors.append(f"{fid}: original fact missing, duplicated or rewritten")
        seen.add(fid)
        if fact["status"] not in {"supported", "qualified", "partial", "unsupported"}:
            errors.append(f"{fid}: unreviewed status")
        if not fact["reason"] or not fact["reviewed_expectation"] or not fact["evidence"]:
            errors.append(f"{fid}: missing review")
    if seen != expected.keys():
        errors.append("39-fact inventory differs from original questions")
    entries = review["facts"] + review.get("additional_question_requirements", [])
    for entry in entries:
        for source in entry["evidence"]:
            relative = Path(source["path"])
            path = (root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root / "knowledge/corpus/huawei-ip"):
                errors.append("evidence path outside corpus")
                continue
            if not path.is_file():
                errors.append(f"missing source: {relative}")
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                errors.append(f"source changed: {relative}")
                continue
            start, end = source["start_line"], source["end_line"]
            lines = raw.decode("utf-8-sig").splitlines()
            if not (type(start) is int and type(end) is int and 1 <= start <= end <= len(lines)):
                errors.append(f"invalid raw coordinates: {relative}")
            elif "\n".join(lines[start - 1:end]) != source["quote"]:
                errors.append(f"raw quote mismatch: {relative}:{start}")
    return errors

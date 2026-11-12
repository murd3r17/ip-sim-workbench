"""Strict, portable scoring of independently produced semantic verdicts.

Semantic truth still requires review; schemas/quote matching cannot prove it.
Report facts, actual claim/citation edges and important-claim coverage separately.
Invalid evaluations fail the case and remain in the case denominator.
"""
import hashlib
import json
import re

from .safety import evaluate

VERSION = "c2.assessment.v1"


def cache_key(request, judge_config):
    """Bind all question, criteria, answer, command and untrimmed context data."""
    payload = {"version": VERSION, "request": request, "judge": judge_config}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def reference_recall(relevant_source_ids, retrieved_source_ids, *, k=5):
    """Exact canonical document IDs only; not lexical/semantic citation support."""
    require(type(k) is int and k > 0, "invalid retrieval cutoff")
    require(all(isinstance(x, str) and x for x in [*relevant_source_ids, *retrieved_source_ids]), "invalid document identity")
    expected = set(relevant_source_ids)
    retrieved = set(retrieved_source_ids[:k])
    return ratio(len(expected & retrieved), len(expected))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keyed(rows, name):
    require(isinstance(rows, list), f"{name}: expected list")
    require(all(isinstance(row, dict) and isinstance(row.get("id"), str)
                and row["id"] for row in rows), f"{name}: invalid id")
    result = {row["id"]: row for row in rows}
    require(len(result) == len(rows), f"{name}: duplicate id")
    return result


def assess_turn(request, verdict):
    result = {"valid": False, "passed": False, "errors": [], "version": VERSION}
    try:
        require(isinstance(request, dict) and isinstance(verdict, dict), "missing request or verdict")
        answer = request.get("answer")
        require(isinstance(answer, str) and bool(answer.strip()), "empty answer")
        require(isinstance(request.get("question"), str) and bool(request["question"].strip()), "empty question")
        require(type(request.get("citation_expected")) is bool, "citation_expected must be boolean")
        context = request.get("generation_context")
        require(isinstance(context, dict) and isinstance(context.get("prompt"), str)
                and bool(context["prompt"]), "missing actual generation context")
        safety = evaluate(answer, request.get("commands"), request.get("protected"))
        result["safety"] = safety
        require(not safety["parse_error"], "invalid safety input")
        facts = keyed(request.get("facts"), "reference facts")
        require(bool(facts), "empty reference facts")
        require(all(isinstance(f.get("text"), str) and f["text"].strip() for f in facts.values()), "empty fact text")
        judged = keyed(verdict.get("facts"), "judged facts")
        require(facts.keys() == judged.keys(), "missing or unexpected fact ids")
        for row in judged.values():
            require(type(row.get("correct")) is bool and isinstance(row.get("reason"), str)
                    and bool(row["reason"].strip()), "illegal semantic fact result")
        sources = keyed(request.get("sources"), "sources")
        for source in sources.values():
            require(isinstance(source.get("text"), str) and bool(source["text"]), "empty source")
            require(source["text"] in context["prompt"], "source not present in actual generation prompt")
        require(verdict.get("claims_complete") is True, "claim inventory not reviewed")
        claims = verdict.get("claims")
        require(isinstance(claims, list) and bool(claims), "empty claim inventory")
        citation_count = supported_count = important_count = covered_count = 0
        spans = set()
        for claim in claims:
            require(isinstance(claim, dict), "invalid claim")
            start, end = claim.get("start"), claim.get("end")
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(answer), "invalid claim span")
            require((start, end) not in spans, "duplicate claim span")
            spans.add((start, end))
            require(type(claim.get("important")) is bool, "invalid importance")
            citations = claim.get("citations")
            require(isinstance(citations, list), "missing citation list")
            seen = set()
            supported = False
            for citation in citations:
                require(isinstance(citation, dict), "invalid citation")
                source_id, marker = citation.get("source_id"), citation.get("marker")
                require(isinstance(source_id, str) and source_id in sources, "unknown cited source")
                require(isinstance(marker, str) and re.fullmatch(r"\[[^\[\]\r\n]+\](?:\([^\r\n]+\))?|【[^【】\r\n]+】", marker)
                        and marker in answer[start:end], "citation not visible at claim")
                require((source_id, marker) not in seen, "duplicate citation edge")
                seen.add((source_id, marker))
                quote = citation.get("source_quote")
                require(isinstance(quote, str) and bool(quote.strip())
                        and quote in sources[source_id]["text"], "citation quote absent from generation source")
                require(type(citation.get("supported")) is bool and isinstance(citation.get("reason"), str)
                        and bool(citation["reason"].strip()), "illegal citation support result")
                citation_count += 1
                supported_count += int(citation["supported"])
                supported |= citation["supported"]
            if claim["important"]:
                important_count += 1
                covered_count += int(supported)
        if request["citation_expected"]:
            require(important_count > 0, "citation task has no important claims")
        result.update(valid=True, fact_accuracy=ratio(sum(f["correct"] for f in judged.values()), len(facts)),
                      citation_precision=ratio(supported_count, citation_count),
                      important_claim_coverage=ratio(covered_count, important_count))
        citation_pass = (not request["citation_expected"] or (
            citation_count > 0 and supported_count / citation_count >= .95
            and important_count > 0 and covered_count / important_count >= .90))
        result["passed"] = not safety["violation"] and result["fact_accuracy"]["rate"] >= .90 and citation_pass
    except (ValueError, TypeError, KeyError) as exc:
        result["errors"].append(str(exc))
    return result


def summarize(cases):
    """Keep invalid cases in pass-rate denominators; retain exact metric counts."""
    groups = {}
    for case in cases:
        group = groups.setdefault(case["group"], {"total": 0, "passed": 0, "invalid": 0,
                                                  "fact_accuracy": ratio(0, 0),
                                                  "citation_precision": ratio(0, 0),
                                                  "important_claim_coverage": ratio(0, 0)})
        group["total"] += 1
        group["passed"] += int(case["passed"])
        group["invalid"] += int(not case["valid"])
        for turn in case["turns"]:
            if not turn["valid"]:
                continue
            for metric in ("fact_accuracy", "citation_precision", "important_claim_coverage"):
                old, current = group[metric], turn[metric]
                group[metric] = ratio(old["numerator"] + current["numerator"], old["denominator"] + current["denominator"])
    for group in groups.values():
        group["pass_rate"] = group["passed"] / group["total"]
    return {"groups": groups, "case_count": len(cases), "metrics_scope": "valid turns only; invalid cases still fail"}


def assess_case(group, requests, verdicts, *, expected_turns):
    result = {"group": group, "valid": False, "passed": False, "turns": [], "errors": []}
    if (type(expected_turns) is not int or expected_turns < 1 or not isinstance(requests, list)
            or not isinstance(verdicts, list) or len(requests) != expected_turns or len(verdicts) != expected_turns):
        result["errors"].append("missing or unexpected turns")
        return result
    result["turns"] = [assess_turn(r, v) for r, v in zip(requests, verdicts)]
    result["valid"] = all(t["valid"] for t in result["turns"])
    # Deliberately independent of group: knowledge and multi-turn have the same veto.
    result["passed"] = result["valid"] and all(t["passed"] for t in result["turns"])
    return result

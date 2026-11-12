import json
from copy import deepcopy
from pathlib import Path

from evaluation.knowledge_basis import verify

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures/evaluation"


def data():
    return [json.loads((FIXTURES / name).read_text(encoding="utf-8"))
            for name in ("knowledge_review.json", "knowledge_questions.json")]


def test_all_original_facts_have_traceable_review_not_automatic_gold():
    review, questions = data()
    assert len(review["facts"]) == 39
    assert review["review_kind"] == "agent_semantic_review_not_human_expert_gold"
    assert verify(review, questions, ROOT) == []
    assert sum(f["status"] == "unsupported" for f in review["facts"]) == 2
    assert sum(f["status"] == "partial" for f in review["facts"]) == 2


def test_source_drift_wrong_lines_and_original_rewrite_are_rejected():
    review, questions = data()
    for field, value in (("sha256", "changed"), ("start_line", 1),
                         ("path", "../ip-sim-source/md/missing.md")):
        modified = deepcopy(review)
        modified["facts"][0]["evidence"][0][field] = value
        assert verify(modified, questions, ROOT)
    review["facts"][0]["original_fact"] = "silently changed standard"
    assert verify(review, questions, ROOT)

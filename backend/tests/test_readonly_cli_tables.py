import pytest

from core.markdown_blocks import unclosed_fence_start
from core.readonly_cli_tables import select_readonly_cli_excerpt


HEADER = " Type      LinkState ID    AdvRouter        Age  Len   Sequence   Metric\r\n"
MATCH = " Network   10.0.23.3       10.0.3.3           259  32    80000003       0\r\n"
OTHER = " Network   10.0.23.3       10.0.9.9           259  32    80000009       2\r\n"
QUERY = "在 Area 0 的 LSDB 表中，LinkState ID 为 10.0.23.3 的记录，其类型、发布路由器和 Metric 是什么？"


def observed_table(*, duplicate=False):
    return ("```text\r\n<R3>display ospf lsdb\r\n  OSPF Process 1 with Router ID 10.0.3.3\r\n"
            "   Link State Database\r\n           Area: 0.0.0.0\r\n" + HEADER
            + "    ---------------------------------------------------------\r\n"
            + "".join(f" Router     10.0.2.{i}        10.0.2.2        1128  72    80000014       1\r\n" for i in range(1, 24))
            + MATCH + (MATCH if duplicate else "") + "           Area: 0.0.0.1\r\n" + HEADER + OTHER + "```")


def test_large_readonly_lsdb_keeps_exact_frame_and_record():
    block = "### PDF 第 23 页\r\n\r\n" + observed_table()
    excerpt = select_readonly_cli_excerpt(block, QUERY)
    assert excerpt and len(excerpt) <= 980
    assert excerpt.startswith("### PDF 第 23 页")
    assert "仅显示所查记录" in excerpt
    assert "<R3>display ospf lsdb\r\n  OSPF Process 1 with Router ID 10.0.3.3\r\n" in excerpt
    assert "Area: 0.0.0.0\r\n" + HEADER + "    ---------------------------------------------------------\r\n" + MATCH in excerpt
    assert OTHER not in excerpt
    assert "Area: 0.0.0.1" not in excerpt
    assert unclosed_fence_start(excerpt) is None


@pytest.mark.parametrize("query", [
    "LinkState ID 为 10.0.23.3 的记录是什么？",  # two Areas have the same key
    QUERY.replace("Area 0", "Area 2"),
    QUERY + " 也比较相邻行。",
    QUERY + " 一共多少条？",
    QUERY + " 排除这行。",
    QUERY + " 这是 R4 的输出吗？",
    QUERY + " 处于进程 2 吗？",
    QUERY + " 故障后字段是什么？",
    QUERY.replace("10.0.23.3", "10.0.23.3/32"),
    QUERY.replace("10.0.23.3", "10.0.23.3extra"),
    QUERY.replace("10.0.23.3", "10.0.3.3"),  # occurs only in AdvRouter
])
def test_query_without_a_unique_compatible_record_keeps_the_full_source(query):
    assert select_readonly_cli_excerpt(observed_table(), query) is None


@pytest.mark.parametrize("replace, replacement", [
    ("<R3>display ospf lsdb", "[R3]ospf 1"),
    ("<R3>display ospf lsdb", "<R3>display ospf lsdb verbose"),
    ("Sequence   Metric", "Sequence   Preference"),
    (MATCH, MATCH + "[R3]ospf 1\r\n"),
])
def test_unrecognized_readback_or_configuration_is_not_cropped(replace, replacement):
    assert select_readonly_cli_excerpt(observed_table().replace(replace, replacement), QUERY) is None


def test_unknown_context_or_duplicate_row_is_not_silently_dropped():
    assert select_readonly_cli_excerpt(observed_table(duplicate=True), QUERY) is None
    assert select_readonly_cli_excerpt(observed_table()[:-3], QUERY) is None
    assert select_readonly_cli_excerpt(observed_table() + "\n\n仅为说明，不代表当时的实际值。", QUERY) is None
    assert select_readonly_cli_excerpt(observed_table().replace(" 80000003       0", " 80000003       0 changed"), QUERY) is None
    assert select_readonly_cli_excerpt(observed_table(), QUERY, max_chars=100) is None

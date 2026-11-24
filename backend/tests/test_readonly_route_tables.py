"""Independent examples of same-page, device-scoped readback."""

import pytest

from core.markdown_blocks import unclosed_fence_start
from core.readonly_route_tables import select_readonly_route_excerpt


_FENCE = chr(96) * 3
_OSPF_HEADER = " Destination        Cost  Type       NextHop      AdvRouter       Area"
R17_ROWS = (
    " 192.0.2.0/25        17  Inter-area   203.0.113.7    198.51.100.17    0.0.0.0",
    " 192.0.2.128/25      18  Inter-area   203.0.113.8    198.51.100.17    0.0.0.0",
)
R19_ROWS = (
    " 192.0.2.0/25         1  Stub         203.0.113.99   198.51.100.19    0.0.0.9",
    " 192.0.2.128/25       2  Stub         203.0.113.98   198.51.100.19    0.0.0.9",
)
ROUTING_QUERY = "在 R17 的汇总前路由表里，192.0.2.0/25 与 192.0.2.128/25 的 NextHop 和 Type 各是什么？"


def _ospf(device, rows):
    return "\n".join((f"<{device}>display ospf routing", "  OSPF Process 1 with Router ID 198.51.100.17",
                      "    Routing Tables", " Routing for Network", _OSPF_HEADER, *rows, " Total Nets: 2"))


def route_page():
    return (f"\n\n执行汇总前分别查看 R17 与 R19 的 OSPF 路由表。\n\n{_FENCE}text\n"
            f"{_ospf('R17', R17_ROWS)}\n{_ospf('R19', R19_ROWS)}\n{_FENCE}")


def test_two_complete_rows_keep_requested_device_and_original_columns():
    page = "### PDF 第 40 页" + route_page()
    excerpt = select_readonly_route_excerpt(page, ROUTING_QUERY)

    assert excerpt and "### PDF 第 40 页" in excerpt
    assert "执行汇总前分别查看" in excerpt
    assert "<R17>display ospf routing" in excerpt and _OSPF_HEADER in excerpt
    assert all(row in excerpt and row in page for row in R17_ROWS)
    assert "<R19>display ospf routing" not in excerpt
    assert not any(row in excerpt for row in R19_ROWS)
    assert unclosed_fence_start(excerpt) is None


def test_same_device_and_keys_use_the_explicitly_labelled_snapshot():
    before = f"{_FENCE}text\n{_ospf('R17', R17_ROWS)}\n{_FENCE}"
    after = f"{_FENCE}text\n{_ospf('R17', R19_ROWS)}\n{_FENCE}"
    page = f"### PDF 第 40 页\n\n执行汇总前在 R17 查表。\n\n{before}\n\n执行汇总后在 R17 再查表。\n\n{after}"
    earlier = select_readonly_route_excerpt(page, ROUTING_QUERY)
    later = select_readonly_route_excerpt(page, ROUTING_QUERY.replace("汇总前", "汇总后"))
    assert earlier and all(row in earlier for row in R17_ROWS) and not any(row in earlier for row in R19_ROWS)
    assert later and all(row in later for row in R19_ROWS) and not any(row in later for row in R17_ROWS)
    assert select_readonly_route_excerpt(page.replace("执行汇总后在 R17 再查表。", "再次在 R17 查表。"), ROUTING_QUERY) is None


@pytest.mark.parametrize("mutate", [
    lambda text: text.replace("### PDF 第 40 页", "### PDF 第 39 页\n\n### PDF 第 40 页"),
    lambda text: text.replace("执行汇总前", "执行汇总后"),
    lambda text: text.replace(R17_ROWS[0], R17_ROWS[0] + "\n" + R17_ROWS[0]),
    lambda text: text.replace(_OSPF_HEADER, _OSPF_HEADER.replace("Cost", "HiddenColumn")),
    lambda text: text.replace("<R19>display ospf routing", "<R17>display ospf routing"),
    lambda text: text.replace("<R17>display ospf routing", "<R17>display ospf routing verbose"),
    lambda text: text[:-3],
])
def test_ambiguous_unknown_and_cross_page_tables_are_not_cropped(mutate):
    assert select_readonly_route_excerpt(mutate("### PDF 第 40 页" + route_page()), ROUTING_QUERY) is None


@pytest.mark.parametrize("query", [
    ROUTING_QUERY.replace("R17", "R170"),
    ROUTING_QUERY.replace("192.0.2.128/25", "203.0.113.128/25"),
    ROUTING_QUERY.replace("192.0.2.128/25", "192.0.2.128/257"),
    ROUTING_QUERY + "所有路由也要看。",
])
def test_query_without_unique_compatible_device_rows_preserves_the_source(query):
    assert select_readonly_route_excerpt("### PDF 第 40 页" + route_page(), query) is None


def _isis(device, suffix, gateway):
    return "\n".join((
        f"[{device}]display isis route ipv6 2001:db8::{suffix}",
        " Route information for ISIS(1)",
        " ISIS(1) Level-2 Forwarding Table",
        " IPV6 Dest.   ExitInterface      NextHop                  Cost   Flags",
        f" 2001:db8::{suffix}/128 GE0/0/7  FE80::{gateway}         8      A/-/-/-",
        " Flags: D-Direct, A-Added to URT",
        " Protect Type: L-Link Protect",
    ))


def test_joint_single_prefix_requires_two_independent_exact_readbacks():
    query = "在 PE15 和 PE12 的 IS-IS 表里要找哪条前缀？"
    separate = (_isis("PE12", "8", "91"), _isis("PE15", "8", "93"))
    body = f"### PDF 第 15 页\n\n{_FENCE}text\n" + "\n".join(separate) + f"\n{_FENCE}"
    excerpt = select_readonly_route_excerpt(body, query)
    assert excerpt and excerpt.count("Level-2 Forwarding Table") == 2
    assert excerpt.index("[PE12]") < excerpt.index("[PE15]")
    assert all(next(line for line in group.splitlines() if "/128" in line) in excerpt for group in separate)
    assert select_readonly_route_excerpt(body.replace(separate[1], _isis("PE15", "9", "93")), query) is None
    assert select_readonly_route_excerpt(body.replace(separate[1], _isis("PE12", "8", "93")), query) is None


@pytest.mark.parametrize(("question_action", "source_action"), [("引入", "重分发"), ("重分发", "引入")])
def test_redistribution_alias_keeps_two_device_rows_at_the_same_stage(question_action, source_action):
    tables = "\n".join((_isis("PE12", "8", "91"), _isis("PE15", "8", "93")))
    note = f"在 ASBR 做路由{source_action}后，查 PE12 和 PE15 的 IPv6 IS-IS 转发表。"
    body = f"### PDF 第 15 页\n\n{note}\n\n{_FENCE}text\n{tables}\n{_FENCE}"
    query = f"业务前缀{question_action}后，在 PE12 和 PE15 的 IS-IS 表里要找哪条精确前缀？"

    excerpt = select_readonly_route_excerpt(body, query)
    assert excerpt and note in excerpt and excerpt.count("Level-2 Forwarding Table") == 2
    assert all(row in excerpt for row in tables.splitlines() if "/128" in row)
    assert select_readonly_route_excerpt(body.replace(f"{source_action}后", f"{source_action}前"), query) is None
    assert select_readonly_route_excerpt(body.replace(f"{source_action}后", "汇总后"), query) is None
    assert select_readonly_route_excerpt(body.replace(f"{source_action}后", "切换后"), query) is None


def test_cross_alias_requires_a_routing_context_in_the_phase_paragraph():
    body = (f"### PDF 第 15 页\n\n作业做重分发后检查附件。\n\n{_FENCE}text\n"
            f"{_isis('PE12', '8', '91')}\n{_FENCE}")
    query = "引入后，在 PE12 的 IS-IS 表里要找哪条精确前缀？"
    assert select_readonly_route_excerpt(body, query) is None

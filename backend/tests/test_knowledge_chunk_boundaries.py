"""Source semantics survive local chunking and the generation context budget."""
import hashlib

from modules.ai_text.context_bundle import prepare_sources, source_documents
from modules.knowledge.local_provider import _split_chunks
from core.markdown_blocks import complete_prefix, retrieval_body


def test_intro_and_empty_sections_are_not_silently_discarded():
    text = '此章先确认范围。\n\n# OSPF\n\n## 未录入内容\n\n## 现场核验\n必须采集。'
    chunks = _split_chunks(text, 80)
    joined = '\n'.join(chunks)
    assert all(line in joined for line in text.splitlines() if line.strip())
    assert _split_chunks('# 只有标题') == ['# 只有标题']


def test_qualifier_in_same_paragraph_is_never_cut_off():
    statement = '接口 Up 可以说明什么？' + '这是管理状态的背景说明。' * 30 + '但不能据此证明业务可达。'
    chunks = _split_chunks('# 接口\n\n' + statement, 100)
    assert any(statement in chunk for chunk in chunks)
    assert not any('接口 Up 可以说明什么？' in chunk and '但不能据此证明业务可达。' not in chunk for chunk in chunks)


def test_fences_keep_hash_comments_blank_lines_and_longer_closing_marker():
    block = '````cli\n# not a chapter\n\ndisplay ospf peer\n```\n# still CLI\n`````'
    chunks = _split_chunks('# OSPF\n\n' + block + '\n\n## 结论\n不能从命令示例推断现场。', 35)
    assert any(block in chunk for chunk in chunks)
    assert len([c for c in chunks if 'still CLI' in c]) == 1
    assert any('## 结论' in c and '命令示例' in c for c in chunks)


def test_large_tables_repeat_exact_headers_and_never_cut_rows():
    header = '| 网络类型 | 是否选举 |\n| --- | --- |'
    rows = [f'| 类型{i}限定条件完整 | 否；不支持{i} |' for i in range(10)]
    chunks = _split_chunks('# 网络\n\n' + header + '\n' + '\n'.join(rows), 90)
    assert len(chunks) > 1
    for row in rows:
        matching = [c for c in chunks if row in c]
        assert len(matching) == 1
        assert header in matching[0]
    assert all(c.startswith('# 网络') for c in chunks)


def test_nested_heading_context_survives_multiple_chunks():
    chunks = _split_chunks('# 路由\n\n## OSPF\n\n### 邻居\n\n' + '\n\n'.join('第%d段说明。' % i for i in range(12)), 60)
    assert len(chunks) > 1
    assert all('# 路由' in c and '## OSPF' in c and '### 邻居' in c for c in chunks)


def test_context_limit_omits_whole_paragraph_with_late_qualifier():
    intro = '已提供的是教材摘要，不能用来证明现场状态。'
    paragraph = '这个配置看似允许访问。' + '背景细节' * 1000 + '但必须先具备管理员权限。'
    sources = prepare_sources([{'filename': 'scope.md', 'text': intro + '\n\n' + paragraph}])
    assert len(sources) == 1
    source = sources[0]
    assert source['content'].strip() == intro
    assert '这个配置看似允许访问' not in source['prompt_text']
    assert source['truncated'] and '不完整' in source['prompt_text']
    assert len(source['prompt_text']) <= 3000
    assert source['version'] == hashlib.sha256(source['content'].encode()).hexdigest()


def test_context_never_advertises_a_partial_cli_block_or_only_a_heading():
    large_code = '# 配置示例\n\n```cli\n' + 'display current-configuration\n' * 200 + '```'
    sources = prepare_sources([{'filename': 'huge.md', 'text': large_code},
                               {'filename': 'usable.md', 'text': '完整的可引用说明。'}])
    assert [s['filename'] for s in sources] == ['usable.md']
    assert source_documents(sources) == [sources[0]['prompt_text']]


def test_context_table_is_atomic_and_does_not_publish_headerless_rows():
    intro = '表格各行必须结合列标题解读。'
    table = '| 含义 | 限制条件 |\n| --- | --- |\n' + '\n'.join('| 可执行 | 仅在独立实验环境中 |' for _ in range(180))
    source = prepare_sources([{'filename': 'table.md', 'text': intro + '\n\n' + table}])[0]
    assert source['content'].strip() == intro
    assert '| 可执行' not in source['prompt_text']


def test_ancestor_context_does_not_multiply_bm25_topic_matches():
    text = '# 源 NAT、目的 NAT、双向 NAT\n\n## 源 NAT\n\n### 源地址转换\n\n只改源地址。'
    body = retrieval_body(text)
    assert body == '### 源地址转换\n\n只改源地址。'
    assert retrieval_body('# 标题\n\n```cli\n# 这是注释\n```') == '# 标题\n\n```cli\n# 这是注释\n```'


def test_prefix_keeps_original_line_endings_and_omits_dangling_heading():
    prefix = '第一段完整。\r\n\r\n'
    content = prefix + '# 下一节\r\n\r\n' + '很长的段落' * 100
    assert complete_prefix(content, 30) == prefix.rstrip()

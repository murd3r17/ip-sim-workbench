"""A-12：编码规范校验脚本自身的测试。

规则：`.ps1` 必须带 UTF-8 BOM（PowerShell 5.1 否则按代码页解码、含中文的脚本直接
解析失败）；`.md`/`.py`/语料等文本必须**不带** BOM（否则 `\\ufeff` 会混进正文，
知识库检索把 BOM 当首字符）。
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"


@pytest.fixture(scope="module")
def check_encoding():
    spec = importlib.util.spec_from_file_location(
        "check_encoding", ROOT / "scripts" / "check_encoding.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ps1_without_bom_is_reported(check_encoding, tmp_path):
    (tmp_path / "a.ps1").write_bytes("Write-Host '中文'".encode("utf-8"))
    problems = check_encoding.check_tree(tmp_path, fix=False)
    assert any("缺少 BOM" in p for p in problems)


def test_markdown_with_bom_is_reported(check_encoding, tmp_path):
    (tmp_path / "a.md").write_bytes(BOM + "# 标题".encode("utf-8"))
    problems = check_encoding.check_tree(tmp_path, fix=False)
    assert any("多余 BOM" in p for p in problems)


def test_fix_normalizes_both_directions(check_encoding, tmp_path):
    ps1 = tmp_path / "b.ps1"
    md = tmp_path / "b.md"
    ps1.write_bytes("Write-Host 1".encode("utf-8"))
    md.write_bytes(BOM + "正文".encode("utf-8"))

    check_encoding.check_tree(tmp_path, fix=True)

    assert ps1.read_bytes().startswith(BOM)
    assert not md.read_bytes().startswith(BOM)
    assert check_encoding.check_tree(tmp_path, fix=False) == []


def test_non_text_suffixes_are_ignored(check_encoding, tmp_path):
    (tmp_path / "image.png").write_bytes(BOM + b"\x89PNG")
    assert check_encoding.check_tree(tmp_path, fix=False) == []


def test_explicit_root_inside_a_skipped_directory_is_still_checked(check_encoding, tmp_path):
    """显式 --root 必须优先于垃圾目录剪枝。

    隔离交付的 pytest basetemp 位于 `.runtime` 下；把临时目录放进 `.runtime`
    曾导致编码检查把整棵树跳过、误报"通过"。
    """
    inner = tmp_path / ".runtime" / "pytest-fixture"
    inner.mkdir(parents=True)
    (inner / "a.ps1").write_bytes("Write-Host 1".encode("utf-8"))
    assert any("缺少 BOM" in item for item in check_encoding.check_tree(inner, fix=False))


def test_skipped_descendants_are_still_pruned(check_encoding, tmp_path):
    for name in (".runtime", "node_modules", "dist"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "a.ps1").write_bytes("Write-Host 1".encode("utf-8"))
    assert check_encoding.check_tree(tmp_path, fix=False) == []


def test_repo_tree_is_clean(check_encoding):
    """当前仓库必须通过编码校验（CI 的同一条命令）。"""
    problems = check_encoding.check_tree(ROOT.parent, fix=False)
    assert problems == [], problems


def test_private_environment_and_private_subtrees_are_never_opened(check_encoding,tmp_path,monkeypatch):
    for name in ['.env','.env.local']:
        (tmp_path/name).write_text('private fixture',encoding='utf-8')
    folder=tmp_path/'private';folder.mkdir();(folder/'credentials.json').write_text('{}',encoding='utf-8')
    (tmp_path/'.env.example').write_text('PUBLIC_TEMPLATE=1',encoding='utf-8')
    original=Path.read_bytes;opened=[]
    def guarded(path):
        assert path.name not in {'.env','.env.local','credentials.json'}
        opened.append(path.name);return original(path)
    monkeypatch.setattr(Path,'read_bytes',guarded)
    assert check_encoding.check_tree(tmp_path,fix=False)==[]
    assert '.env.example' in opened

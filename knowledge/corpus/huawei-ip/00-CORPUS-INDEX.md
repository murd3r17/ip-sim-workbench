# IP仿真知识库语料索引

- 工作台副本：`knowledge/corpus/huawei-ip/`
- 源目录是权威：改文只改 `<corpus-src>\md`，再跑工作台 `scripts/sync-corpus.ps1`，再经 AnythingLLM 适配器入库
- 知识库：**AnythingLLM**，135 篇已入库（工作区 `ip-ops-kb`）

## 书籍

| 目录 | 类型 |
|---|---|
| `HCIA-Security-V4.0-Training/` | training |
| `HCIP-Security-V4.0-Training/` | training |
| `HCIE-Security-V2.0-Training/` | training |
| `HCIE-Security-V2.0-Lab/` | lab |
| `HCIP-Datacom-Core-Training/` | training |
| `HCIP-Datacom-Core-Lab/` | lab |
| `HCIP-Datacom-Advanced-RS-Training/` | training |
| `HCIP-Datacom-Advanced-RS-Lab/` | lab |
| `HCIE-Datacom-V1.0-Training/` | training |
| `HCIE-Datacom-V1.0-Lab/` | lab |

## 工具

- `tools/pdf_to_md.py` — PDF 转 MD
- `tools/organize_kb.py` — 结构化整理（可选）
- `tools/clean_md_corpus.py` — 去注释杂质
- `tools/LLM_EDIT_STANDARD.md` — 大模型改文标准

# 知识库语料（华为 IP / 安全）

- 路径：`knowledge/corpus/huawei-ip/`
- 权威源：`<corpus-src>\md`（清理后的培训/实验 Markdown）
- 入库文件：各书目录下 `NN-*.md`
- 不入库：`00-index.md`、`00-CORPUS-INDEX.md`

## 使用方式

知识库为 **AnythingLLM Desktop（端口 3001）** + 本地 Ollama `nomic-embed-text` 嵌入。不要运行 `scripts/archive-ragflow/`。

1. 运行 `scripts\start-local-windows.ps1`（自动拉起 Ollama 11434 与 AnythingLLM 3001；已监听则跳过）
2. 在 AnythingLLM 创建 API Key，写入根 `.env` 的 `KNOWLEDGE_API_KEY`
3. 工作台：`KNOWLEDGE_PROVIDER=anythingllm`，问答走检索 + DeepSeek 生成
4. 新增/改文后：先改 `ip-sim-source`，再跑 `scripts/sync-corpus.ps1`。**工作台知识库页没有上传按钮**，不要经页面入库；适配器 upload 仅供脚本/排障。

## 注意

- 请保留章节 YAML frontmatter（`track` / `doc_type` 等）
- 修改语料后重新入库；勿把 AnythingLLM 内解析结果当源

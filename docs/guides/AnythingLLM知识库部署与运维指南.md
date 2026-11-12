# AnythingLLM 知识库部署与运维指南

> 工作台知识库：AnythingLLM Desktop（Windows）+ 本机 Ollama `nomic-embed-text` 嵌入 + DeepSeek 对话/视觉。
> 本文只写现行配置与排障。不要启动 `scripts/archive-ragflow/`。

---

## 工作台独立审校说明（2026-11-06）

原教材保留原样。工作台对已核对的具体简写/错误，在生成来源旁附独立说明，配置在 `backend/modules/knowledge/reviewed_source_notes.json`：按文件名和原句匹配，给出审校内容、标准章节链接、核对日期和内容版本。不得把用户上传的自报元数据当作审校授权。

说明与原文一起计入原有上下文预算；引用弹窗分别显示“审校补充 · 非教材原文”和原文。请求保存当时说明，历史读取仍核验归属、当前资料可访问性及文档身份，不静默替换成新说明。修改说明后重启工作台后端使其加载；无需改写远端教材、重新嵌入或修改原语料。只有 provider 返回文件名与匹配原句时才附说明，不能据本地验证宣称所有远端检索已通过。

增加说明前必须有具体反例、原始片段与权威依据，并做受影响问题、相邻问题及来源预算/撤权回归。只补经核对的必要条件，不扩建一套课程。目前的针对性修正是 RS 响应时机/目的地址及 NSSA 转换与缺省路由的区别；整体 C 阶段质量仍待验收。

## 1. 组件组成

| 组件 | 位置 | 端口 | 说明 |
|------|------|------|------|
| AnythingLLM Desktop | `C:\Users\<user>\AppData\Local\Programs\AnythingLLM\AnythingLLM.exe` | 3001（后端 API）/ 8888（collector） | Squirrel 安装，Electron + 内嵌 node 后端 |
| 本地存储（文档/向量） | `%APPDATA%\anythingllm-desktop\storage` | - | hotdir / documents / lancedb / engines |
| 系统 Ollama | `C:\Users\<user>\AppData\Local\Programs\Ollama\ollama.exe` | 11434 | **唯一** Ollama 实例（0.32.15），只做嵌入 |
| 嵌入模型 | nomic-embed-text（274MB，768 维） | 11434 | Ollama 本地 |
| 对话/视觉 LLM | DeepSeek `deepseek-v4-flash-vision-exp`（云端 API） | - | 文字问答 + 图片识别，复用工作台 DeepSeek key |

### 关键约束（务必遵守）

1. **只用系统 Ollama（11434）一个实例**。AnythingLLM 内置引擎（`engines\ollama\llm.exe`，0.20.7）与系统 Ollama（0.32.15）共用/冲突模型目录（manifests/blobs），会导致模型被"踩空"（`ollama list` 变空、`model not found`）。
   - 对话 provider 不要配 `anythingllm_ollama`（内置引擎）；文字/视觉走 DeepSeek 云端（`generic-openai`），嵌入走本地 Ollama（`ollama`），两者互不干扰。
2. **文档必须使用 ASCII 文件名**。AnythingLLM 对中文文件名存在 bug（处理失败、json url 悬空）。
3. **hotdir 是易失目录**：AnythingLLM collector 每次启动会清空 `storage\hotdir`。文档 json 的 url 若指向 hotdir，重启后源文件丢失、无法重新嵌入。
   - 解决：源文件统一存放在 `storage\documents\uploads\`（持久目录），json url 指向那里。
4. **引导三件套**：`ffmpeg` + `ffprobe` + license 缺一则反复 bootstrap 下载（源慢）。手动从 GitHub 下载放好后不会再触发。

### 为什么对话/视觉用 DeepSeek 云端

- **嵌入（向量化）必须本地 Ollama**：DeepSeek API 不提供 embedding 端点，RAG 检索的文本→向量只能由嵌入模型完成。
- **问答/视觉走 DeepSeek**：`deepseek-v4-flash-vision-exp` 已上线（OpenAI 兼容），支持文字 + 图片（base64 data URL / 外链 URL / Files API），图片最多 384 token/张、上限约 800×800 等效缩放，走 `generic-openai` provider 接入。
- AnythingLLM 的 `deepseek` provider 在 1.16.0 **硬编码丢弃图片附件**（`DeepSeek does not support vision - stripped image attachments`），因此必须用 `generic-openai` provider（其 `GenericOpenAiLLM` 原生将 attachments 转为 `image_url` 块）。

---

## 2. AnythingLLM .env 配置（关键项）

位置：`%APPDATA%\anythingllm-desktop\storage\.env`

```ini
LLM_PROVIDER='generic-openai'
GENERIC_OPEN_AI_BASE_PATH='https://api.deepseek.com/v1'
GENERIC_OPEN_AI_API_KEY='<set-in-local-.env>'
GENERIC_OPEN_AI_MODEL_PREF='deepseek-v4-flash-vision-exp'
GENERIC_OPEN_AI_MAX_TOKENS='8192'
GENERIC_OPEN_AI_MODEL_TOKEN_LIMIT='131072'
EMBEDDING_ENGINE='ollama'
EMBEDDING_BASE_PATH='http://127.0.0.1:11434'
EMBEDDING_MODEL_PREF='nomic-embed-text'
EMBEDDING_MODEL_MAX_CHUNK_LENGTH='8192'
OLLAMA_EMBEDDING_BATCH_SIZE='1'
VECTOR_DB='lancedb'
SERVER_PORT='3001'
COLLECTOR_PORT='8888'
```

> ⚠️ 嵌入模型键名是 `EMBEDDING_MODEL_PREF`；`EMBEDDING_MODEL` 是内置模型（NativeEmbedder）的键，误配会报 "No embedding model was set"。

修改 .env 后需重启 AnythingLLM 才会生效（杀掉全部 `AnythingLLM*` 进程再启动 exe）。

---

## 3. Ollama 模型管理

```powershell
# 查看模型
C:\Users\<user>\AppData\Local\Programs\Ollama\ollama.exe list

# 拉取模型（走系统 11434，下载到 %USERPROFILE%\.ollama\models）
C:\Users\<user>\AppData\Local\Programs\Ollama\ollama.exe pull nomic-embed-text
# （qwen3-vl:4b-instruct 已弃用——视觉已切换 DeepSeek 云端；如需回退本地视觉可重新拉取）
```

- `ollama.exe serve` 常驻 11434（开机自启或手动 `ollama.exe serve`）。
- 千万**不要**从 AnythingLLM 界面下载/管理模型（界面走内置引擎 0.20.7）。
- 对话/视觉模型在 Ollama 侧：**无**（已切 DeepSeek 云端）。Ollama 只保留 nomic-embed-text 供嵌入。

### 验证 embed 可用

```json
POST http://127.0.0.1:11434/api/embed
{"model":"nomic-embed-text","input":"测试"}
→ {"embeddings":[[...768维]]}
```

---

## 4. 工作台配置

位置：`D:\work\ip-sim-workbench\.env`

```ini
KNOWLEDGE_PROVIDER=anythingllm
KNOWLEDGE_BASE_URL=http://127.0.0.1:3001
KNOWLEDGE_API_KEY=<set-in-local-.env>
KNOWLEDGE_WORKSPACE_SLUG=ip-ops-kb
KNOWLEDGE_DATASET_ID=1
KNOWLEDGE_TOP_K=8
KNOWLEDGE_SIMILARITY_THRESHOLD=0.2
```

- `KNOWLEDGE_API_KEY`：AnythingLLM 桌面版 API Key（界面 **设置 → 开发人员 → API Keys** 生成）。
- `KNOWLEDGE_WORKSPACE_SLUG`：工作区 slug（本例 `ip-ops-kb`）。

---

## 5. 数据布局（storage 目录）

```
%APPDATA%\anythingllm-desktop\storage\
├── .env                         # 后端配置（见第 2 节）
├── hotdir\                      # ⚠️ 易失：collector 每次启动清空
├── documents\
│   ├── custom-documents\        # 文档 json（约 135 个：title 保留中文原名，url 指向 uploads）
│   └── uploads\                 # ✅ 持久：doc-NNN.md（ASCII 源文件）
├── lancedb\ip-ops-kb.lance\     # 向量存储
├── engines\ollama\              # 内置引擎（弃用；仅留存不启动）
├── logs\backend-*.log           # 后端日志
└── logs\collector-*.log         # collector 日志（"hot directory wiped" 在此可见）
```

语料源与命名映射：`D:\work\ip-sim-workbench\knowledge\corpus\huawei-ip\`（146 个 md）+ `anythingllm-name-map.txt`（doc-NNN.md ↔ 中文原名）。

---

## 6. 向量搜索与问答（工作台侧契约）

| 端点 | 说明 |
|------|------|
| `GET /api/v1/ai/knowledge/health` | provider 健康 + document_count |
| `GET /api/v1/ai/knowledge/documents` | 文档列表（中文标题来自 metadata） |
| `POST /api/v1/ai/knowledge/search` `{question, top_k}` | 语义检索，返回原始 chunk |
| `POST /api/v1/ai/ask` `{question}` | RAG 检索 + LLM 生成回答 |
| `POST /api/v1/ai/knowledge/upload` | 适配器仍保留；**知识库页无上传 UI**，静态语料走 sync-corpus，实时文件走右侧助手 |
| `DELETE /api/v1/ai/knowledge/documents/{doc_id:path}` | 删除文档（doc_id 形如 `custom-documents/xxx.json`） |

工作台适配器：`backend\modules\knowledge\anythingllm.py`（upload 后自动持久化到 uploads 并修正 json url；delete 后清理源文件 + json）。

---

## 7. 启动顺序（开机自启）

`scripts\start-local-windows.ps1`（以及包装脚本 `start-all.ps1`）按以下顺序自动拉起，已监听则跳过：

1. 系统 Ollama（`ollama.exe serve`，11434，等待最多 30s）
2. AnythingLLM Desktop（3001，Electron 冷启等待最多 90s）
3. MySQL 13307 → MinIO 9002 → 后端 8000 → 前端 5173

找不到知识库 exe 时 WARN 跳过，不挡住工作台四件套。默认 `stop-local-windows.ps1` 不停 Ollama/AnythingLLM（桌面应用），加 `-IncludeKnowledge` 才停。

---

## 8. 故障排查速查表

| 现象 | 根因 | 处置 |
|------|------|------|
| 后端日志 `No embedding model was set` | `.env` 用了 `EMBEDDING_MODEL`（错键） | 改为 `EMBEDDING_MODEL_PREF='nomic-embed-text'` 并重启 |
| 后端日志 `model "nomic-embed-text" not found` | 模型未拉/被内置引擎踩空 | `ollama list` 检查；缺失则 `ollama pull`；确认 11434 是系统 ollama |
| 界面处理文档失败、chunks=0 | hotdir 被清空 / json url 指向已删除文件 | 重建 uploads 源文件 + 修正 json url（参照第 5 节） |
| 中文名文档不处理 | AnythingLLM 中文文件名 bug | 全部改为 ASCII 命名 |
| 上传后重启文档消失 | collector 启动清空 hotdir | 工作台适配器已自动持久化到 uploads（v6 起） |
| AnythingLLM 白屏 / spawn ENOENT | 绿色解压版不完整 | 用官方 Squirrel 安装器重装 |
| 首次启动卡在引擎下载 | ffmpeg/ffprobe/license 缺失 | 手动下载放 `storage\engines\[ffmpeg|ffprobe|license]` |
| 删除文档 404 | doc_id 含 `/` 被 path 参数截断 | 路由已用 `{doc_id:path}` |
| `curl --data @file` 报 invalid character | PowerShell 吃引号 | 用 `Invoke-RestMethod` 或写文件后 `--data @file` |

---

## 9. PDF 图文入库（DeepSeek 视觉逐页识别）—— ⚠️ 已停用

> **2026-08 决策：此方案已停用。** AnythingLLM 只做静态**文字**知识库（135 篇教材 md），
> 不再入库 PDF/图文版；实时文件/截图分析走右侧 AI 助手「文件」按钮（DeepSeek 直连，秒级）。
> 以下内容仅作历史记录，勿重新启用。

AnythingLLM 的 pdf-parse 只提取文本层，**读不了 PDF 中的图**（拓扑/截图/图表）。要连图也入库，走"页渲染 → 视觉识别 → 图文 md"管线：

```
PDF → WinRT 渲染(页→1400px PNG) → pymupdf 压缩(≈770px) → DeepSeek-v4-flash-vision-exp 逐页识别 → NN-00-pdf-vision-全文.md → AnythingLLM 入库
```

| 项目 | 实测值（HCIP-Datacom-Advanced 实验手册 127 页） |
|------|------|
| 产出 | 309KB / 15.8 万字（命令输出完整复现） |
| 单页 token | ≈496（输入 387 + 输出 109）；DeepSeek 图缩放上限 384 token/图 |
| 价格 | $0.22/M 输入、$0.66/M 输出 |
| 质量 | 文字+命令+图表架构均准确（认证体系图/拓扑图可读） |
| 全量 10 本 8143 页 | ≈400 万 token ≈ ¥10-25，时间 1-2 小时（后台并发 4） |

工具脚本（.runtime/，当前不执行）：
- `render-pdf-winrt.py`（WinRT 渲染页图，系统原生）
- `pdf-vision-to-md.py`（DeepSeek 视觉识别 → md，asyncio 并发 + 断点续跑）
- `batch-pdf-vision.py`（单本全流程：渲染→压缩→识别→md）

> ⚠️ 全量入库前注意：与已有按章节 md 语料内容重叠（检索会命中两处）。图文版定位为"补充图表信息"，勿删原章节 md。

---

## 10. 相关资源汇总

| 资源 | 路径 |
|------|------|
| 迁移脚本 | `D:\work\ip-sim-workbench\.runtime\migrate-to-anythingllm.py` |
| 重建/修正脚本 | `D:\work\ip-sim-workbench\.runtime\rebuild-hotdir.py`、`migrate-to-stable-dir.py` |
| 命名映射表 | `D:\work\ip-sim-workbench\knowledge\corpus\anythingllm-name-map.txt` |
| 工作台适配器 | `backend\modules\knowledge\anythingllm.py` |
| 后端源码（排查用） | `C:\Users\<user>\AppData\Local\Programs\AnythingLLM\resources\backend\server.js` |
| 备份 | 仓库根 `.env`（唯一凭据来源，已 gitignore）；**不要**再留 `.env.bak-*` 明文备份（2026-09-09 已删除 `.env.bak-anythingllm`） |

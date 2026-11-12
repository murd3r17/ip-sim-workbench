"""全局配置 - 通过环境变量或.env文件加载"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_WORKBENCH_ROOT = Path(__file__).resolve().parents[2]
_ENV_CANDIDATES = (
    _WORKBENCH_ROOT / ".env",
    Path(__file__).resolve().parents[1] / ".env",  # backend/.env
)


class Settings(BaseSettings):
    """全局配置"""
    # 应用基础
    app_name: str = "IP仿真运维管理工作站"
    # Product version for new installations; existing explicit settings are preserved.
    app_version: str = "v7.0"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # 数据库
    db_host: str = "127.0.0.1"
    db_port: int = 13307
    db_name: str = "sim_workspace"
    db_user: str = "sim_admin"
    db_password: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    # 数据库后端：mysql（默认，生产/日常）| sqlite（最小运行模式，无需安装 MySQL）
    db_backend: str = "mysql"
    # 完整连接串覆盖（优先级最高，例如 sqlite+aiosqlite:///D:/path/db.sqlite3）
    db_url: str = ""
    # sqlite 文件路径；留空则用 <repo>/.runtime/sim_workspace.db
    db_sqlite_path: str = ""
    # 是否允许空库在启动时按 Alembic 初始化（SQLite 默认允许；已有库须显式升级）
    db_auto_create: bool = False

    # MinIO
    minio_endpoint: str = "127.0.0.1:9002"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "sim-workstation"
    minio_secure: bool = False

    # JWT：默认 2 小时（与 .env.example 一致；A-14 此前代码默认 480 分钟）
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120

    # 设备凭证
    device_default_username: str = ""
    device_default_password: str = ""
    device_default_enable: str = ""
    # 设备执行模式：ssh（真机/eNSP，默认）| sim（离线模拟，无 eNSP 时演示/测试）
    device_mode: str = "ssh"

    # Fernet密钥
    fernet_key: str = ""

    # 初始管理员（bootstrap_local*.py 创建/重置 admin 时使用）
    # 留空则自动生成随机密码并只在首次创建时打印一次；明文口令禁止写入仓库。
    admin_username: str = "admin"
    admin_password: str = ""

    # LLM配置
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-flash"
    llm_api_key: str = ""
    llm_max_tokens: int = 16384
    llm_temperature: float = 0.3
    # A5（设计 §8 配置内容补齐）：业务调用超时（秒）。健康检查仍用短超时，见 core/llm_provider.py
    llm_timeout: int = 120
    # 备用模型（主模型不可用时自动切换；留空则维持静态模板降级）
    llm_fallback_model: str = ""
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    # DeepSeek 思考模式（reasoning_content）；其它厂商无此字段时会被忽略或关闭
    llm_thinking_enabled: bool = True
    llm_reasoning_effort: str = "high"
    # 视觉模型（OpenAI 兼容 image_url）：AI 助手图片/截图理解；空则关闭图片功能
    llm_vision_model: str = ""
    llm_vision_mime_whitelist: str = "image/png,image/jpeg,image/webp,image/gif"

    # 网络执行
    ssh_connect_timeout: int = 10
    ssh_command_timeout: int = 30
    # SSH 主机密钥校验：默认关闭（eNSP/虚拟镜像频繁重装，严格校验会挡住正常使用）；
    # 生产或真实设备环境建议开启，并配置 ssh_known_hosts
    ssh_strict_host_key: bool = False
    ssh_known_hosts: str = ""
    deploy_max_concurrent: int = 5
    deploy_batch_size: int = 5
    deploy_batch_interval: float = 2.0

    # 拓扑发现（LLDP 并发采集用；深度/超时随未接线的 discovery 模块一并移除）
    topology_concurrent_ssh: int = 5

    # 监控
    monitor_collect_interval: int = 60
    monitor_batch_size: int = 5
    monitor_batch_interval: float = 2.0
    monitor_device_timeout: int = 60
    monitor_retention_days: int = 30
    monitor_scheduler_enabled: bool = False

    # eNSP：工作台经 SSH 直连映射端口，不读 ENSP_API_*（已从 Settings 删除）
    ensp_health_check_interval: int = 300

    # WebSSH 走 FastAPI WS，无独立 7681 端口（webssh_port 已删除）
    webssh_max_sessions_per_user: int = 5
    webssh_log_retention_days: int = 30

    # RAG 历史路径（仅 ragwebui / ragflow 遗留代码读取；当前 knowledge_provider=anythingllm 不走这些）
    rag_base_url: str = "http://localhost:80"
    rag_username: str = "admin"
    rag_password: str = ""
    rag_jwt_token: str = ""
    rag_default_kb_id: str = "1"

    # KnowledgeProvider：anythingllm（当前）/ ragflow / ragwebui（历史）
    knowledge_provider: str = "anythingllm"
    knowledge_base_url: str = "http://127.0.0.1:3001"
    knowledge_api_key: str = ""
    knowledge_workspace_slug: str = "ip-ops-kb"
    knowledge_workspace_id: str = ""  # legacy alias
    knowledge_dataset_id: str = ""  # RAGFlow dataset id（仅 ragflow 路径）
    knowledge_corpus_dir: str = ""  # absolute or relative path to corpus; empty = default
    knowledge_top_k: int = 8
    knowledge_similarity_threshold: float = 0.2
    knowledge_max_upload_mb: int = 20
    knowledge_max_upload_files: int = 200
    knowledge_request_timeout: int = 180
    # AnythingLLM 本地存储根目录（documents\custom-documents / documents\uploads / hotdir）
    # Windows 默认 %APPDATA%\anythingllm-desktop\storage，可在 .env 用 KNOWLEDGE_ANYTHINGLLM_STORAGE 覆盖
    knowledge_anythingllm_storage: str = ""

    # 4D 受控下发
    deploy_simulate_only: bool = True
    # 首次配置默认拒绝写设备；由接收方确认真实基线后导出本库白名单。
    deploy_allowlist_device_ids: str = ""
    deploy_allowlist_mgmt_ips: str = ""
    deploy_allowlist_topology_id: int = 0
    deploy_allowlist_baseline_version: int = 0
    # 设备写锁（设计 §15.3）：TTL 与过期检查间隔。只有"未进入执行"的锁会被自动释放，
    # 正在 executing/verifying 的任务其锁不会被清（见 DeployService.release_expired_locks）
    deploy_lock_ttl_seconds: int = 3600
    deploy_lock_expire_check_seconds: int = 300

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 日志：默认写到 <仓库根>/.runtime/logs（绝对路径，与启动脚本把 CWD 设为 backend/ 无关；
    # A-14 此前默认 "logs" 是相对 CWD 的，换目录写日志就跑到别处去了）
    log_level: str = "INFO"
    log_dir: str = str(_WORKBENCH_ROOT / ".runtime" / "logs")
    log_retention_days: int = 30

    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _ENV_CANDIDATES if p.exists()) or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()

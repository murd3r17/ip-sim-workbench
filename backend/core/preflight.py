"""启动配置预检：把"缺哪些键、缺了会怎样"在启动日志里说清楚。

背景（2026-09-09 审计 A-15）：此前只有 JWT_SECRET_KEY 缺失会硬失败，
其余必填键（DB_PASSWORD / LLM_API_KEY / 设备凭据 / 知识库 key）缺失时静默降级，
新用户看到的是"功能时好时坏"，不知道缺什么。

约定：
- level="fatal"：该模式下无法正常工作，启动应中止；
- level="warn"：功能降级但服务可用（如未配 LLM key → AI 功能不可用）；
- level="info"：提示性信息。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ConfigIssue:
    level: str          # fatal | warn | info
    key: str            # 相关配置键
    message: str        # 给用户看的中文说明
    hint: str = ""      # 修复建议

    def as_dict(self) -> dict:
        return {"level": self.level, "key": self.key, "message": self.message, "hint": self.hint}


@dataclass(slots=True)
class PreflightResult:
    issues: list[ConfigIssue] = field(default_factory=list)

    @property
    def fatal(self) -> list[ConfigIssue]:
        return [item for item in self.issues if item.level == "fatal"]

    @property
    def warnings(self) -> list[ConfigIssue]:
        return [item for item in self.issues if item.level == "warn"]

    def as_dicts(self) -> list[dict]:
        return [item.as_dict() for item in self.issues]

    def summary(self) -> str:
        if not self.issues:
            return "配置检查通过"
        parts = []
        for item in self.issues:
            mark = {"fatal": "!!", "warn": "WARN", "info": "INFO"}.get(item.level, "-")
            parts.append(f"[{mark}] {item.key}: {item.message}" + (f" → {item.hint}" if item.hint else ""))
        return "\n".join(parts)


def check_startup_config(settings) -> PreflightResult:
    """按当前模式检查配置完整性。"""
    result = PreflightResult()
    backend = (getattr(settings, "db_backend", "mysql") or "mysql").strip().lower()
    db_url = (getattr(settings, "db_url", "") or "").strip()

    # ── 数据库 ──────────────────────────────────────────────
    if not db_url and backend != "sqlite":
        if not settings.db_password:
            result.issues.append(ConfigIssue(
                "fatal", "DB_PASSWORD",
                "MySQL 模式未配置数据库口令，无法连接",
                "在根 .env 填 DB_PASSWORD，或改用 DB_BACKEND=sqlite（最小运行模式）",
            ))
    if backend == "sqlite" or db_url.startswith("sqlite"):
        result.issues.append(ConfigIssue(
            "info", "DB_BACKEND",
            "使用 SQLite 最小运行模式（空库按迁移初始化，已有库检查结构版本）",
            "需要 MySQL 时改 DB_BACKEND=mysql 并填 DB_PASSWORD",
        ))

    # ── 安全 ────────────────────────────────────────────────
    if not settings.jwt_secret_key:
        result.issues.append(ConfigIssue(
            "fatal", "JWT_SECRET_KEY", "未配置 JWT 密钥，无法签发/校验登录令牌",
            "在根 .env 设置 JWT_SECRET_KEY（scripts/bootstrap-local.ps1 会自动生成）",
        ))
    elif len(settings.jwt_secret_key) < 32:
        result.issues.append(ConfigIssue(
            "warn", "JWT_SECRET_KEY", "JWT 密钥长度不足 32 字符，建议换更强的密钥",
            "生成：python -c \"import secrets;print(secrets.token_urlsafe(48))\"",
        ))
    if not settings.fernet_key:
        result.issues.append(ConfigIssue(
            "warn", "FERNET_KEY", "未配置 Fernet 密钥，将拒绝加密保存设备口令",
            "在根 .env 设置 FERNET_KEY（scripts/bootstrap-local.ps1 会自动生成）",
        ))

    # ── LLM ────────────────────────────────────────────────
    if not settings.llm_api_key:
        result.issues.append(ConfigIssue(
            "warn", "LLM_API_KEY", "未配置对话模型密钥，AI 助手/教练/配置生成会明确提示不可用",
            "在根 .env 填 LLM_API_KEY（如 DeepSeek），或接受降级",
        ))

    # ── 知识库 ──────────────────────────────────────────────
    provider = (getattr(settings, "knowledge_provider", "") or "").strip().lower()
    if provider == "anythingllm" and not settings.knowledge_api_key:
        result.issues.append(ConfigIssue(
            "warn", "KNOWLEDGE_API_KEY", "AnythingLLM 模式未配置 API Key，知识库检索不可用",
            "填 KNOWLEDGE_API_KEY，或改用 KNOWLEDGE_PROVIDER=local（本地语料关键词检索）",
        ))
    elif provider == "local":
        result.issues.append(ConfigIssue(
            "info", "KNOWLEDGE_PROVIDER",
            "使用本地语料关键词检索（无需 AnythingLLM/Ollama）",
            "需要向量检索时改回 anythingllm 并配置 KNOWLEDGE_API_KEY",
        ))

    # ── 设备 ────────────────────────────────────────────────
    mode = (getattr(settings, "device_mode", "ssh") or "ssh").strip().lower()
    if mode == "sim":
        result.issues.append(ConfigIssue(
            "info", "DEVICE_MODE", "设备为离线模拟模式（无真实 SSH 连接）",
            "接真实设备时改 DEVICE_MODE=ssh 并填 DEVICE_DEFAULT_USERNAME/PASSWORD",
        ))
    elif not settings.device_default_username or not settings.device_default_password:
        result.issues.append(ConfigIssue(
            "warn", "DEVICE_DEFAULT_USERNAME/PASSWORD",
            "SSH 模式但未配置设备默认凭据，健康检查/采集/终端会失败",
            "在根 .env 填 DEVICE_DEFAULT_*，或改用 DEVICE_MODE=sim",
        ))

    return result

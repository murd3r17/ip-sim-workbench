"""JWT签发/校验、密码哈希、凭证加密"""
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from fastapi import HTTPException
from core.config import get_settings

logger = None  # lazy init to avoid circular import


def _get_logger():
    global logger
    if logger is None:
        from core.logger import get_logger
        logger = get_logger("security")
    return logger


# bcrypt 只取前 72 字节：bcrypt 5.x 对超长口令直接抛 ValueError，
# 4.x 之前是静默截断。这里显式拒绝，避免"哈希成功但永远验不过"。
BCRYPT_MAX_BYTES = 72


def _password_bytes(password: str) -> bytes:
    raw = (password or "").encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"密码不能超过 {BCRYPT_MAX_BYTES} 字节（当前 {len(raw)} 字节）")
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, username: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "username": username, "role": role, "exp": expire,
               "iat": now, "ver": token_version}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="无效Token")


class CredentialEncryptor:
    """设备凭证Fernet加密器。

    未配置 FERNET_KEY 时**拒绝加密**（此前直接返回明文，等于把设备口令明文入库），
    decrypt 对历史明文数据保持兼容。
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        settings = get_settings()
        if settings.fernet_key:
            from cryptography.fernet import Fernet
            self._fernet = Fernet(settings.fernet_key.encode())
        else:
            self._fernet = None
            _get_logger().error(
                "fernet_key_missing",
                hint="FERNET_KEY 未配置：拒绝加密设备口令；请在根 .env 配置（scripts/bootstrap-local.ps1 会自动生成）",
            )
        self._initialized = True

    @property
    def configured(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise RuntimeError(
                "FERNET_KEY 未配置，拒绝以明文保存设备口令。"
                "请在根 .env 设置 FERNET_KEY（可用 scripts/bootstrap-local.ps1 自动生成）。"
            )
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if self._fernet is None or ciphertext is None:
            return ciphertext
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except Exception as exc:  # noqa: BLE001
            # 密钥轮换后旧密文无法解开：给出明确提示而不是 500 栈
            _get_logger().error("credential_decrypt_failed", error=type(exc).__name__)
            raise RuntimeError(
                "设备口令解密失败：FERNET_KEY 可能已轮换。请重新录入设备凭据。"
            ) from exc


credential_encryptor = CredentialEncryptor()

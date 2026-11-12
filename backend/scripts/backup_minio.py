#!/usr/bin/env python3
"""备份 MinIO 对象到本地目录（.runtime/backup/<ts>/minio/）。

依赖 backend venv 的 minio 包。凭据从根 .env 读取（MINIO_ACCESS_KEY / MINIO_SECRET_KEY）。
用法：backend/.venv/Scripts/python.exe backend/scripts/backup_minio.py <输出目录>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")
load_dotenv(WORKBENCH_ROOT / ".env", override=False)

from minio import Minio  # noqa: E402


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "").resolve()
    if not out_dir.is_dir():
        print(f"输出目录不存在: {out_dir}", file=sys.stderr)
        return 1

    endpoint = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9002")
    access = os.getenv("MINIO_ACCESS_KEY", "")
    secret = os.getenv("MINIO_SECRET_KEY", "")
    if not access or not secret:
        print(
            "[minio] 未配置 MINIO_ACCESS_KEY / MINIO_SECRET_KEY（根 .env），"
            "跳过 MinIO 备份（不使用内置默认凭据）",
            file=sys.stderr,
        )
        return 3
    client = Minio(endpoint, access_key=access, secret_key=secret, secure=False)

    total = 0
    errors = 0
    for bucket in client.list_buckets():
        bucket_name = bucket.name
        target = out_dir / "minio" / bucket_name
        target.mkdir(parents=True, exist_ok=True)
        try:
            objects = list(client.list_objects(bucket_name, recursive=True))
        except Exception as exc:
            print(f"[minio] 列出 bucket {bucket_name} 失败: {exc}", file=sys.stderr)
            errors += 1
            continue
        if not objects:
            print(f"[minio] bucket {bucket_name}: 空（无对象）")
            continue
        for obj in objects:
            if obj.is_dir:
                continue
            dest = target / obj.object_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                client.fget_object(bucket_name, obj.object_name, str(dest))
                total += 1
            except Exception as exc:
                print(f"[minio] {bucket_name}/{obj.object_name} 下载失败: {exc}", file=sys.stderr)
                errors += 1
    print(f"[minio] 完成: 备份 {total} 个对象, 失败 {errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

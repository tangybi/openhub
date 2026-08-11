"""Cloudflare R2 对象存储（S3 兼容，boto3）。粘贴正文 + 附件落 R2，短链接 302 直出。

boto3 为同步阻塞调用，全部经 asyncio.to_thread 包装避免阻塞事件循环。
R2 未配置时 storage.get_paste_store() 返回 None，路由层抛 503；app 仍可启动。
"""

from __future__ import annotations

import asyncio

from ..config import settings
from ..logger_config import get_logger
from .base import PasteStore

logger = get_logger()


class R2PasteStore(PasteStore):
    def __init__(self) -> None:
        import boto3  # 延迟导入：R2 未配置时启动不崩

        self.bucket = settings.r2_bucket

        # 归一化 endpoint：控制台复制的 S3 端点可能带 bucket 路径（.../bucket），
        # 而 boto3 的 Bucket= 参数会自己拼路径，这里去掉尾部 /<bucket>。
        endpoint = settings.r2_endpoint.rstrip("/")
        if endpoint.lower().endswith(f"/{self.bucket.lower()}"):
            endpoint = endpoint[: -len(f"/{self.bucket}")]
            logger.warning("R2_ENDPOINT 带了 bucket 路径，已自动去掉：%s", endpoint)

        # 归一化 public_base_url：允许省略 https:// 协议头。
        public_base = settings.r2_public_base_url.strip().rstrip("/")
        if "://" not in public_base:
            public_base = f"https://{public_base}"

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key,
            aws_secret_access_key=settings.r2_secret_key,
            region_name="auto",
        )
        self.public_base_url = public_base

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        cache_control: str = "public, max-age=3600",
    ) -> None:
        def _put() -> None:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl=cache_control,
            )

        await asyncio.to_thread(_put)

    async def get_bytes(self, key: str) -> bytes | None:
        def _get() -> bytes | None:
            try:
                resp = self._client.get_object(Bucket=self.bucket, Key=key)
            except self._client.exceptions.NoSuchKey:
                return None
            try:
                return resp["Body"].read()
            finally:
                resp["Body"].close()

        return await asyncio.to_thread(_get)

    async def delete_object(self, key: str) -> None:
        def _del() -> None:
            self._client.delete_object(Bucket=self.bucket, Key=key)

        await asyncio.to_thread(_del)

    def public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{key}"

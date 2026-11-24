"""本地向量模型客户端

懒加载 sentence-transformers 模型（默认 BAAI/bge-small-zh-v1.5，CPU 可跑），
提供查询/文档向量编码；模型不可用时返回 None，检索自动降级为纯关键词。
"""

import os
import threading

# 国内网络直连 huggingface.co 会超时导致模型加载失败（本地缓存明明完整）。
# 统一走 hf-mirror 镜像兜底：有缓存时即使镜像抖动也能用 cached commit hash 加载成功。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_model = None  # 懒加载的 sentence-transformers 模型单例
_load_failed = False  # 加载失败标记，避免每次请求重复尝试


def _get_model():
    """懒加载模型单例；失败置标记并返回 None（进程内不再重试）"""
    global _model, _load_failed
    if not settings.embedding.enabled or _load_failed:
        return None
    if _model is not None:
        return _model
    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"开始加载向量模型: {settings.embedding.model_name}")
            model = SentenceTransformer(settings.embedding.model_name, device="cpu")
            _model = model
            logger.info("向量模型加载完成 ✅")
        except Exception as exc:  # 模型缺失/下载失败等
            _load_failed = True
            logger.warning(f"向量模型加载失败，语义检索将降级为纯关键词: {exc!r}")
        return _model


def encode_texts(texts: list[str]) -> np.ndarray | None:
    """批量编码文本为归一化向量矩阵 (n, dim)；模型不可用返回 None"""
    model = _get_model()
    if model is None or not texts:
        return None
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)


def encode_query(text: str) -> np.ndarray | None:
    """编码单条查询向量 (dim,)；模型不可用返回 None"""
    result = encode_texts([text]) if text.strip() else None
    return None if result is None else result[0]

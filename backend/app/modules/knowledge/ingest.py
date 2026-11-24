"""知识库入库：读取 parse 脚本产出的 JSON，切块写入数据库"""

import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .schemas import KbIngestResult
from .service import KnowledgeService, parse_content_list

logger = get_logger(__name__)

# 后端项目根目录：app/modules/knowledge/ingest.py 向上三级
BACKEND_ROOT = Path(__file__).resolve().parents[3]
# parse 脚本的解析产物目录：data/knowledge/<category>/<source_name>.json
PARSED_DIR = BACKEND_ROOT / "data" / "knowledge"


def derive_product_name(source_name: str) -> str:
    """从文件名推导产品名：去掉「条款」「费率表」等后缀"""
    name = source_name
    for suffix in ("条款", "费率表"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name or source_name


async def ingest_from_parsed_dir(session: AsyncSession) -> KbIngestResult:
    """遍历解析产物目录，逐份入库（幂等，重复执行会重建切块）"""
    service = KnowledgeService(session)
    ingested = 0
    total_chunks = 0
    failed: list[str] = []

    json_files = sorted(PARSED_DIR.glob("*/*.json"))
    if not json_files:
        logger.warning(f"未找到解析产物，请先运行 scripts/parse_kb.py parse：{PARSED_DIR}")
        return KbIngestResult(ingested=0, total_chunks=0, failed=[])

    for json_path in json_files:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"解析产物读取失败 {json_path.name}: {exc!r}")
            failed.append(json_path.stem)
            continue

        raw_items = data.get("content_list") or []
        blocks = parse_content_list(raw_items)
        doc = await service.ingest_document(
            source_name=data.get("source_name") or json_path.stem,
            category=data.get("category") or json_path.parent.name,
            file_path=data.get("file_path") or "",
            blocks=blocks,
            error=data.get("error"),
        )
        doc.product_name = derive_product_name(doc.source_name)
        ingested += 1
        total_chunks += doc.chunk_count
        if doc.parse_status == "failed":
            failed.append(doc.source_name)
        logger.info(f"入库 {doc.source_name}: {doc.parse_status}, {doc.chunk_count} 块")

    return KbIngestResult(ingested=ingested, total_chunks=total_chunks, failed=failed)

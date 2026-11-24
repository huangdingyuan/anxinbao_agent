"""知识库构建脚本：MinerU 解析 PDF -> 解析产物 JSON -> 切块入库

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts/parse_kb.py parse    # 仅调用 MinerU 解析（联网，较慢）
    .venv\\Scripts\\python.exe scripts/parse_kb.py ingest   # 仅把已有解析产物切块入库
    .venv\\Scripts\\python.exe scripts/parse_kb.py all      # 解析 + 入库
    .venv\\Scripts\\python.exe scripts/parse_kb.py parse --force   # 忽略已有产物强制重新解析

解析产物：data/knowledge/<category>/<source_name>.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
# 允许独立运行时导入 app 包
sys.path.insert(0, str(BACKEND_ROOT))
RAW_ROOT = BACKEND_ROOT / "08.保险条款" / "08.保险条款" / "data" / "raw"
PARSED_DIR = BACKEND_ROOT / "data" / "knowledge"

CATEGORIES = ("kb", "rate_table")  # kb 保险条款 / rate_table 费率表
EXTRACT_TIMEOUT = 900  # 单份 PDF 解析超时（秒）


def parse_all(force: bool = False) -> None:
    """调用 MinerU 云端接口解析全部 PDF，产物落盘为 JSON"""
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
    from mineru import MinerU

    pdf_files: list[tuple[str, Path]] = []
    for category in CATEGORIES:
        raw_dir = RAW_ROOT / category
        if not raw_dir.exists() and category == "rate_table":
            # 兼容源目录复数命名：rate_tables
            raw_dir = RAW_ROOT / "rate_tables"
        for pdf_path in sorted(raw_dir.glob("*.pdf")):
            pdf_files.append((category, pdf_path))
    print(f"共 {len(pdf_files)} 份 PDF 待解析")

    client = MinerU()
    ok = failed = skipped = 0
    for index, (category, pdf_path) in enumerate(pdf_files, 1):
        source_name = pdf_path.stem
        out_path = PARSED_DIR / category / f"{source_name}.json"
        if out_path.exists() and not force:
            print(f"[{index}/{len(pdf_files)}] 跳过（已有产物）：{source_name}")
            skipped += 1
            continue
        print(f"[{index}/{len(pdf_files)}] 解析中：{source_name} ...", flush=True)
        try:
            result = client.extract(str(pdf_path), timeout=EXTRACT_TIMEOUT)
            if result.state != "done":
                raise RuntimeError(f"解析未完成: state={result.state} err={result.error}")
            payload = {
                "source_name": source_name,
                "category": category,
                "file_path": str(pdf_path),
                "markdown": result.markdown,
                "content_list": result.content_list,
                "error": None,
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            ok += 1
            print(f"  -> 完成（markdown {len(result.markdown or '')} 字 / content_list {len(result.content_list or [])} 块）")
        except Exception as exc:
            # 失败也落盘，入库时记为 failed 文档，避免反复重试
            payload = {
                "source_name": source_name,
                "category": category,
                "file_path": str(pdf_path),
                "markdown": "",
                "content_list": [],
                "error": repr(exc),
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            failed += 1
            print(f"  -> 失败：{exc!r}")
    print(f"解析完成：成功 {ok} / 失败 {failed} / 跳过 {skipped}")


async def ingest_all() -> None:
    """把解析产物切块入库（复用模块内 ingest 逻辑）"""
    from app.common.database import AsyncSessionFactory
    from app.modules.knowledge.ingest import ingest_from_parsed_dir

    async with AsyncSessionFactory() as session, session.begin():
        result = await ingest_from_parsed_dir(session)
    print(f"入库完成：文档 {result.ingested} 份 / 切块 {result.total_chunks} 条 / 失败 {len(result.failed)}")
    if result.failed:
        print(f"失败清单：{result.failed}")


async def backfill_embeddings() -> None:
    """为存量无向量块补算语义向量（分批，幂等）"""
    from app.common.database import AsyncSessionFactory
    from app.modules.knowledge.embedder import _get_model

    if _get_model() is None:
        print("向量模型不可用，无法补算（检查 EMBEDDING_ENABLED 与模型下载）")
        return
    from app.modules.knowledge.service import KnowledgeService

    async with AsyncSessionFactory() as session:
        service = KnowledgeService(session)
        total = await service.backfill_embeddings()
    print(f"向量补算完成：{total} 块")


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库构建：MinerU 解析 + 切块入库")
    parser.add_argument(
        "step",
        choices=["parse", "ingest", "backfill", "all"],
        help="执行步骤（backfill: 为存量块补算语义向量）",
    )
    parser.add_argument("--force", action="store_true", help="忽略已有解析产物，强制重新解析")
    args = parser.parse_args()
    if args.step in ("parse", "all"):
        parse_all(force=args.force)
    if args.step in ("ingest", "all"):
        import asyncio
        asyncio.run(ingest_all())
    if args.step == "backfill":
        import asyncio
        asyncio.run(backfill_embeddings())


if __name__ == "__main__":
    main()

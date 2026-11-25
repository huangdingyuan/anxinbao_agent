"""检索增强：产品库匹配 + 本地条款知识库检索。

两个来源各自独立容错，任一失败只记录日志并跳过，不影响问答主流程。

费率表查询走精确行检索：费率表是「保险期间|计划|性别|交费期|投保年龄|保险费|...」的
纯数字网格，纯语义/关键词检索无法按「投保年龄=30」精确命中目标行，因此对含
年龄+性别+交费期的保费问题，额外用正则捞取确切行喂给模型。
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.products.models import Product

logger = get_logger(__name__)

# 问题关键词 -> 产品分类编码
CATEGORY_KEYWORDS = {
    "medical": ("医疗", "住院", "百万医疗", "报销"),
    "critical_illness": ("重疾", "大病", "癌症"),
    "life": ("寿险", "身故", "分红", "增额", "终身寿"),
    "accident": ("意外", "磕碰", "摔伤"),
}

# 命中候选集的最少得分
MIN_SCORE = 2
# 送给模型挑选的候选产品数上限
MAX_CANDIDATES = 8
# 问题参与匹配的 bigram 数上限，防止超长问题拖慢匹配
MAX_QUESTION_BIGRAMS = 60


def _bigrams(text: str) -> list[str]:
    """提取相邻二字片段，用于中文关键词匹配"""
    cleaned = "".join(ch for ch in text if ch.isalnum())
    return [cleaned[i:i + 2] for i in range(len(cleaned) - 1)]


def _detect_category(question: str) -> str | None:
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in question for kw in keywords):
            return category
    return None


async def retrieve_products(session: AsyncSession, question: str) -> list[Product]:
    """在产品库中做简单关键词匹配，返回最相关的产品（不命中则返回空）"""
    result = await session.execute(
        select(Product).where(Product.status == "active")
    )
    products = result.scalars().all()
    if not products:
        return []

    category = _detect_category(question)
    # 问题 bigram 拆到两边用：问产品名用全量，问产品描述截断防超长
    q_bigrams = _bigrams(question)[:MAX_QUESTION_BIGRAMS]
    q_in_desc = q_bigrams[:30]

    scored = []
    for product in products:
        score = 0
        if category and product.category == category:
            score += 3
        # 产品名片段出现在问题里（用户点名某产品）
        name_bigrams = _bigrams(product.name)
        score += sum(2 for bg in name_bigrams if bg in question)
        # 问题片段出现在产品名/描述里（泛需求，如“百万医疗险推荐”）
        score += sum(1 for bg in q_bigrams if bg in product.name)
        if product.description:
            score += sum(1 for bg in q_in_desc if bg in product.description) // 2
        if score >= MIN_SCORE:
            scored.append((score, product))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [product for _, product in scored[:MAX_CANDIDATES]]


def _longest_match_pos(name: str, answer: str, min_len: int = 4) -> int:
    """返回 name 在 answer 中最长匹配的起始位置（匹配长度 >= min_len），未命中返回 -1。

    模型回答常用产品简称（如“达尔文12号”），滑动窗口取最长可匹配片段。
    """
    for length in range(len(name), min_len - 1, -1):
        for start in range(len(name) - length + 1):
            pos = answer.find(name[start:start + length])
            if pos >= 0:
                return pos
    return -1


def filter_mentioned(products: list, answer: str) -> list:
    """从候选产品中筛选出回答里实际提及的，按首次提及位置排序。

    匹配规则：产品名与回答的最长公共片段（>= 4 字），兼容简称与括号后缀省略。
    products 元素支持 ORM Product 或 payload dict（LangGraph 图状态用 dict 保证可序列化）。
    """
    matched: list[tuple[int, object]] = []
    for product in products:
        name = product.name if hasattr(product, "name") else product["name"]
        pos = _longest_match_pos(name, answer)
        if pos >= 0:
            matched.append((pos, product))
    matched.sort(key=lambda pair: pair[0])
    return [product for _, product in matched]


async def retrieve_products_from_db(question: str) -> list[Product]:
    """使用独立短会话检索产品库，供流式响应内部调用"""
    from app.common.database import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        return await retrieve_products(session, question)


# 条款（kb）块内容截断上限；费率表（rate_table）块已在检索端裁到目标行，给全量不截断
KB_CHUNK_CONTENT_LIMIT = 1500


async def retrieve_kb_chunks(question: str, top_k: int = 4) -> list[dict]:
    """使用独立短会话在本地条款知识库中检索，任一失败降级为空"""
    if not question:
        return []
    try:
        from app.common.database import AsyncSessionFactory
        from app.modules.knowledge.service import KnowledgeService

        async with AsyncSessionFactory() as session:
            items = await KnowledgeService(session).search(question, top_k)
        return [item.model_dump(mode="json") for item in items]
    except Exception as exc:
        logger.warning(f"条款知识库检索失败，降级为无条款参考: {exc!r}")
        return []


# ---------- 费率表精确行检索 ----------
# 不同产品费率表列布局不同，常见两种：
#   格式一：保险期间 | 计划 | 性别 | 交费期 | 投保年龄 | 保险费 | EM25…（保险费=每千元保额年交保费）
#   格式二：保额(元) | 计划 | 性别 | 交费期 | 投保年龄 | 保险费(元)（保险费=该保额实际年交保费）
# 因此把命中指纹的原始行 + 产品表头直接交给模型解读，不做单一正则硬解析。
RATE_COLUMN_LEGEND = (
    "费率表为原文表格，列布局因产品而异，请先读表头确认列含义与保费单位："
    "若表头为「保险期间|计划|性别|交费期|投保年龄|保险费|EM…」，则保险费是每千元保额的年交保费，"
    "实际保费=保险费×保额(千元=保额万×10)；若首列为保额数值，则保险费是该保额对应的实际年交保费。"
    "EM25/50/75/100 为次标体（额外死亡率）加费档位，健康标准体取基础保险费列。"
    "半年交=年交×0.52，季交=年交×0.27，月交=年交×0.09。"
)

# 触发问价是否为「保费/费率」类问题
RATE_QUERY_SIGNAL = ("保费", "费率", "多少钱", "一年交", "年交", "年缴", "交多少", "价格", "一年多少钱")
# 表头行判定关键词（用于从原文捕获真实列头）
_HEADER_KEYWORDS = ("保险费", "投保年龄", "保额", "计划", "保险期间")
# 喂给模型的精确行上限（同维度不同计划的行数较多，截断避免上下文爆炸）
RATE_PRECISE_LINE_LIMIT = 20


def parse_rate_query(question: str) -> dict | None:
    """从问题中提取费率查询维度；缺年龄/性别/交费期则不做精确检索（降级语义）"""
    if not question or not any(s in question for s in RATE_QUERY_SIGNAL):
        return None
    age_m = re.search(r"(\d{1,3})\s*岁", question)
    gender = "男" if "男" in question else ("女" if "女" in question else None)
    pay_m = re.search(r"(趸交|\d{1,2}\s*年交|\d{1,2}\s*年缴)", question)
    if not (age_m and gender and pay_m):
        return None
    period = "终身" if "终身" in question else None
    if period is None:
        m = re.search(r"保至\s*(\d{1,3})\s*岁", question)
        if m:
            period = f"保至{m.group(1)}岁"
    insured_m = re.search(r"(\d{1,3})\s*万", question)
    return {
        "age": age_m.group(1),
        "gender": gender,
        "pay": pay_m.group(1).replace(" ", "").replace("年缴", "年交"),
        "period": period,
        "insured_wan": int(insured_m.group(1)) if insured_m else None,
    }


def _longest_common_substr_len(name: str, question: str, cap: int = 20) -> int:
    """文档名与问题的最长公共子串长度（兼容简称/括号后缀省略），上限 cap 防止超长"""
    max_len = min(len(name), cap)
    for length in range(max_len, 0, -1):
        for start in range(len(name) - length + 1):
            if name[start:start + length] in question:
                return length
    return 0


async def retrieve_rate_table_rows(question: str) -> list[dict]:
    """费率表精确行检索：按 性别|交费期|投保年龄 命中确切行，返回与 kb_refs 同结构的列表"""
    spec = parse_rate_query(question)
    if spec is None:
        return []
    try:
        from app.common.database import AsyncSessionFactory
        from sqlalchemy import text

        async with AsyncSessionFactory() as session:
            # 1) 找出名称与问题匹配的费率表文档（用于结果偏好），找不到则放宽到全部
            all_docs = (
                await session.execute(
                    text(
                        "SELECT source_name, product_name FROM kb_documents "
                        "WHERE category='rate_table' AND parse_status='parsed'"
                    )
                )
            ).all()
            if not all_docs:
                return []
            # 只保留与问题最长公共子串最大的文档（避免「复星联合」这类保险公司前缀
            # 被多个产品共享导致串台）；最长匹配 < 4 字视为未指定产品，放宽到全部
            name_scores = [
                (source_name, _longest_common_substr_len(source_name or "", question))
                for source_name, _product_name in all_docs
            ]
            max_score = max((s for _, s in name_scores), default=0)
            matched_names = {
                source_name for source_name, s in name_scores if s >= 4 and s == max_score
            }

            # 2) 找含目标行指纹「| 性别 | 交费期 | 投保年龄 |」的费率表块（用 LIKE，避免正则方言差异）
            fingerprint = f"%| {spec['gender']} | {spec['pay']} | {spec['age']} |%"
            res = await session.execute(
                text(
                    "SELECT c.content, c.page_no, c.heading, d.source_name, d.product_name "
                    "FROM kb_chunks c JOIN kb_documents d ON d.id=c.document_id "
                    "WHERE d.category='rate_table' AND d.parse_status='parsed' "
                    "AND c.content LIKE :pat"
                ),
                {"pat": fingerprint},
            )
            # 3) 从命中块中抽出含指纹的原始行 + 产品表头（不做单一正则硬解析，兼容不同列布局）
            fingerprint_sub = f"| {spec['gender']} | {spec['pay']} | {spec['age']} |"
            lines: list[str] = []
            seen: set[str] = set()
            header_lines: list[str] = []
            header_seen: set[str] = set()
            ref_src = ref_product = ref_page = ref_heading = None
            rows = list(res)
            # 名称匹配的文档排前，保证表头/参考来源来自用户询问的产品
            rows.sort(key=lambda r: (0 if r[3] in matched_names else 1,))
            for content, page_no, heading, source_name, product_name in rows:
                # 若有名称匹配的文档，只采用这些文档的行
                if matched_names and source_name not in matched_names:
                    continue
                if ref_src is None:
                    ref_src, ref_product, ref_page, ref_heading = source_name, product_name, page_no, heading
                for raw in content.splitlines():
                    line = raw.strip()
                    if not line or "|" not in line:
                        continue
                    # 捕获表头行（含列说明关键词），最多保留 2 条去重
                    if any(kw in line for kw in _HEADER_KEYWORDS) and line not in header_seen:
                        header_seen.add(line)
                        if len(header_lines) < 2:
                            header_lines.append(line)
                        continue
                    if fingerprint_sub not in line:
                        continue
                    if line in seen:
                        continue
                    seen.add(line)
                    lines.append(line)
            if not lines:
                return []

            # 期间软过滤：指定了期间且存在含该期间的行时，只保留这些行；
            # 若所有行都不含期间（如某些产品表无期间列），则不排除
            if spec["period"]:
                period_lines = [ln for ln in lines if spec["period"] in ln]
                if period_lines:
                    lines = period_lines

            # 统一排序：用户询问保额（格式二首列）对应的行最优先 → 含「终身」→ 其余按文本
            target = str(spec["insured_wan"] * 10000) if spec["insured_wan"] else None

            def _sort_key(ln: str) -> tuple:
                is_target = target is not None and (
                    ln.strip().startswith(target + " |") or f"| {target} |" in ln
                )
                return (0 if is_target else 1, 0 if "终身" in ln else 1, ln)

            lines.sort(key=_sort_key)
            lines = lines[:RATE_PRECISE_LINE_LIMIT]

            content_lines: list[str] = []
            if header_lines:
                content_lines.extend(header_lines)
            content_lines.extend(lines)
            if spec["insured_wan"]:
                content_lines.append(
                    f"（用户询问保额：{spec['insured_wan']}万。请按表头单位换算："
                    f"若保险费为每千元费率，则乘以 {spec['insured_wan'] * 10}；"
                    f"若保险费已是对应保额的实际保费，则直接取值。）"
                )
            return [
                {
                    "document_id": None,
                    "source_name": ref_src,
                    "product_name": ref_product,
                    "category": "rate_table",
                    "page_no": (ref_page or 0) + 1,
                    "heading": ref_heading or "费率表（精确行）",
                    "content": "\n".join(content_lines),
                    "score": 1.0,
                }
            ]
    except Exception as exc:
        logger.warning(f"费率表精确行检索失败，降级: {exc!r}")
        return []


CATEGORY_LABELS = {
    "medical": "医疗险",
    "critical_illness": "重疾险",
    "life": "寿险",
    "accident": "意外险",
}


def _pget(p, key: str):
    """产品字段访问：兼容 ORM（legacy 路径）与 payload dict（LangGraph 图状态）"""
    return p[key] if isinstance(p, dict) else getattr(p, key, None)


def build_context_block(products: list, kb_refs: list[dict] | None = None) -> str:
    """把检索结果拼成系统提示词末尾的参考信息块"""
    lines = ["以下是可供参考的信息："]
    if kb_refs:
        lines.append("【条款参考】（本地知识库中的保险条款/费率表原文，回答涉及条款细节时以此为准）")
        has_rate_table = any(ref.get("category") == "rate_table" for ref in kb_refs)
        if has_rate_table:
            lines.append(RATE_COLUMN_LEGEND)
        for ref in kb_refs:
            source = ref.get("product_name") or ref.get("source_name") or "未知文档"
            heading = ref.get("heading") or "未标注章节"
            lines.append(f"- 来源：{source}（{heading}，第 {ref.get('page_no', 1)} 页）")
            content = ref.get("content") or ""
            # 费率表精确行已是裁剪后的目标数据，给全量；条款块按上限截断
            if ref.get("category") != "rate_table":
                content = content[:KB_CHUNK_CONTENT_LIMIT]
            if content:
                lines.append(f"  原文摘录：{content}")
    if products:
        lines.append("【产品库参考】（平台在售产品）")
        for p in products:
            category = CATEGORY_LABELS.get(_pget(p, "category"), _pget(p, "category"))
            lines.append(f"- {_pget(p, 'name')}（{category}，承保公司：{_pget(p, 'insurer')}）")
            if _pget(p, "description"):
                lines.append(f"  产品简介：{_pget(p, 'description')}")
            if _pget(p, "highlights"):
                lines.append(f"  产品亮点：{'；'.join(_pget(p, 'highlights'))}")
    return "\n".join(lines)

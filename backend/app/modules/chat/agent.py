"""LangGraph 保险顾问 Agent：route 分类 -> retrieve 检索 -> generate 流式生成。

确定性 RAG 流水线图（非 ReAct）：三路检索规则（费率精确行、RRF 融合、产品 bigram）
已针对回归行为调优，由图显式编排而非交给模型决定，保证 SSE 时序与答案质量稳定。

状态通道全部 JSON-safe（payload dict），可被 AsyncPostgresSaver 序列化。
"""

import functools
from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.config import settings
from app.core.logging import get_logger

from .rag import gather_references
from .retrieval import (
    _detect_category,
    build_context_block,
    parse_rate_query,
)

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "你是「安心保」平台的智能保险顾问，名叫安安。"
    "你的职责是用通俗易懂的语言解答用户的保险相关问题，包括险种科普、投保建议、理赔流程等。"
    "回答要求：1. 条理清晰，适当分段或使用短列表；2. 不夸大产品收益，不做虚假承诺；"
    "3. 涉及具体产品时提醒用户以条款原文为准；4. 使用中文回答。"
    "5. 若下方提供了【产品库参考】：它是平台在售产品候选，请结合用户的年龄、预算、保障需求，"
    "从中挑选 2-3 款最适合的产品明确推荐，并在回答中使用产品的完整名称（与参考信息中一致）逐一说明推荐理由，"
    "不要只做泛泛的选购科普；"
    "6. 若提供了【条款参考】：它是平台知识库中的条款原文摘录，涉及保障责任、免责、犹豫期等条款细节时以此为准作答，"
    "并提醒用户可查阅对应条款原文；不得编造参考信息中不存在的产品或数据；"
    "7. 若【条款参考】中包含费率表（且给出了列说明/精确行）：说明数据已命中，"
    "必须根据列说明（保险费=每千元保额年交保费，实际保费=保险费×保额千元）"
    "为用户算出具体保费数值并明确回答，不得回复“没有对应数据”或只做泛泛解释；"
    "若精确行未覆盖用户指定的全部维度（如某计划/保额），要说明已覆盖的部分并指出缺哪一档；"
    "若没有参考信息且问题涉及具体产品推荐，建议用户描述需求以便进一步推荐。"
)

# 送给模型的最近消息条数（不含本次提问）
HISTORY_WINDOW = 10

# 条款咨询信号词
CLAUSE_SIGNALS = (
    "条款", "免责", "除外", "理赔", "等待期", "犹豫期", "冷静期", "保障责任",
    "报销", "续保", "免赔", "现金价值", "退保", "责任", "生效", "宽限期",
)
# 闲聊/寒暄信号（短问题且不含任何保险领域词时跳过检索）
GREETING_SIGNALS = ("你好", "您好", "哈喽", "hello", "hi", "谢谢", "再见", "你是谁", "能做什么", "会什么")


def classify_route(question: str) -> tuple[str, list[str]]:
    """纯规则问题分类（零 LLM 调用），返回 (route, tasks)。

    - rate    : 含「年龄+性别+交费期」的费率/保费问题 -> 三路全开（费率精确行 + 条款 + 产品）
    - product : 险种关键词命中 -> 产品 + 条款
    - clause  : 条款信号词命中 -> 条款 + 产品
    - general : 寒暄闲聊 -> 不检索
    - 其余    : 保守起见与现状一致，开产品 + 条款两路
    """
    if not question or not question.strip():
        return "general", []
    if parse_rate_query(question) is not None:
        return "rate", ["rates", "clauses", "products"]
    lowered = question.lower()
    if (
        len(question) <= 12
        and not any(kw in question for kw in CLAUSE_SIGNALS)
        and _detect_category(question) is None
        and any(g in lowered for g in GREETING_SIGNALS)
    ):
        return "general", []
    if _detect_category(question):
        return "product", ["products", "clauses"]
    if any(kw in question for kw in CLAUSE_SIGNALS):
        return "clause", ["clauses", "products"]
    return "mixed", ["products", "clauses"]


class AdvisorState(TypedDict, total=False):
    """图状态：每轮全量覆盖（无 reducer），通道值必须 JSON 可序列化"""

    question: str          # 本次提问
    history: list[dict]    # [{"role","content"}]，来自 prepare_ask 的最近 N 条
    route: str             # rate / product / clause / general
    tasks: list[str]       # 启用的检索路 ["rates","clauses","products"] 的子集
    products: list[dict]   # 候选产品 payload（product_payload 形状）
    kb_refs: list[dict]    # 条款/费率引用（KbSearchItem dict 形状）
    context: str           # build_context_block 文本
    answer: str            # 完整回答
    error: str | None


_llm = None  # ChatDeepSeek 懒加载单例


def get_chat_model():
    """ChatDeepSeek 单例工厂。

    注意：api_key 必须显式传入——langchain-deepseek 默认只读 os.environ，
    而本项目 .env 由 pydantic-settings 加载、不注入 os.environ。
    """
    global _llm
    if _llm is None:
        from langchain_deepseek import ChatDeepSeek

        _llm = ChatDeepSeek(
            model=settings.llm.chat_model,
            api_key=settings.llm.api_key,
            base_url=settings.llm.base_url,
        )
    return _llm


def route_node(state: AdvisorState) -> dict:
    route, tasks = classify_route(state.get("question", ""))
    logger.info(f"Agent route={route} tasks={tasks}")
    return {"route": route, "tasks": tasks}


async def retrieve_node(state: AdvisorState) -> dict:
    """三路并行检索（费率行优先去重），产出候选产品与条款引用"""
    products, kb_refs = await gather_references(state["question"], state.get("tasks", []))
    context = build_context_block(products, kb_refs) if (products or kb_refs) else ""
    return {"products": products, "kb_refs": kb_refs, "context": context}


async def generate_node(state: AdvisorState, llm=None) -> dict:
    """ChatDeepSeek 流式生成。token 由 graph astream(stream_mode="messages") 自动外流，
    节点内只负责收集全文写入状态。"""
    model = llm or get_chat_model()
    context = state.get("context") or ""
    messages: list[BaseMessage] = [
        SystemMessage(content=SYSTEM_PROMPT + (("\n\n" + context) if context else ""))
    ]
    for msg in state.get("history", []):
        if msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
        else:
            messages.append(HumanMessage(content=msg["content"]))
    messages.append(HumanMessage(content=state["question"]))

    parts: list[str] = []
    async for chunk in model.astream(messages):
        if isinstance(chunk.content, str) and chunk.content:
            parts.append(chunk.content)
    return {"answer": "".join(parts)}


def _next_node(state: AdvisorState) -> str:
    return "retrieve" if state.get("tasks") else "generate"


def build_advisor_graph(checkpointer=None, llm=None) -> CompiledStateGraph:
    """组装保险顾问图。llm 注入便于单测替身；checkpointer 传 AsyncPostgresSaver 实例。"""
    builder = StateGraph(AdvisorState)
    builder.add_node("route", route_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node(
        "generate",
        functools.partial(generate_node, llm=llm) if llm is not None else generate_node,
    )
    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route", _next_node, {"retrieve": "retrieve", "generate": "generate"}
    )
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    return builder.compile(checkpointer=checkpointer)

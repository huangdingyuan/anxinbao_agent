import asyncio
import json
from collections.abc import AsyncGenerator
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_runtime import get_advisor_graph
from app.core.config import settings
from app.core.exceptions import BizError, NotFoundError
from app.core.logging import get_logger
from app.common.database import AsyncSessionFactory
from app.modules.conversation.models import ChatThread
from app.modules.insurance_plan.repository import InsurancePlanRepository
from app.modules.insurance_plan.service import InsurancePlanService, build_interrupt
from app.modules.products.models import Product
from .agent import HISTORY_WINDOW, SYSTEM_PROMPT
from .models import ChatMessage
from .repository import ChatMessageRepository
from .retrieval import (
    build_context_block,
    filter_mentioned,
    retrieve_kb_chunks,
    retrieve_products_from_db,
    retrieve_rate_table_rows,
)

logger = get_logger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 方案决策对应的用户消息文案（与前端乐观渲染保持一致）
DECISION_MESSAGES = {
    "approve": "确认保存保险方案",
    "reject": "取消保存保险方案",
}
DECISION_REPLIES = {
    "approve": (
        "好的，已为你保存这份保障方案。你可以点击方案中的「投保」按钮进入投保流程，"
        "保费以实际试算结果为准。后续如需调整保障内容或预算，随时告诉我。"
    ),
    "reject": (
        "好的，这份方案先不保存。你可以告诉我想调整的部分，比如预算范围、险种偏好或具体产品，"
        "我会重新为你推荐更合适的组合。"
    ),
}


def _product_item(p: Product) -> dict:
    """产品信息的通用 payload 结构"""
    return {
        "id": p.id,
        "product_id": p.id,
        "name": p.name,
        "category": p.category,
        "insurer": p.insurer,
        "image_url": p.image_url,
        "description": p.description or "",
        "highlights": p.highlights or [],
    }


class ChatService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve_thread(self, user_id: int, thread_id: UUID | None, content: str) -> UUID:
        """定位会话：thread_id 为空时自动创建新会话，否则校验归属"""
        async with self.session.begin():
            if thread_id is None:
                thread = ChatThread(user_id=user_id, title=content[:20] or "新会话")
                self.session.add(thread)
                await self.session.flush()
                return thread.id
            thread = await self.session.get(ChatThread, thread_id)
            if thread is None or thread.user_id != user_id:
                raise NotFoundError("会话不存在")
            return thread_id

    async def list_messages(self, user_id: int, thread_id: UUID) -> list[ChatMessage]:
        """查询会话的消息历史，会话不存在或越权时抛出 NotFoundError"""
        thread = await self.session.get(ChatThread, thread_id)
        if thread is None or thread.user_id != user_id:
            raise NotFoundError("会话不存在")
        result = await ChatMessageRepository(self.session).find_by_thread(thread_id)
        return list(result)

    async def get_pending_interrupt(self, user_id: int, thread_id: UUID) -> dict | None:
        """获取会话中待确认的方案中断事件，没有则返回 None"""
        thread = await self.session.get(ChatThread, thread_id)
        if thread is None or thread.user_id != user_id:
            raise NotFoundError("会话不存在")
        plan = await InsurancePlanRepository(self.session).find_pending_by_thread(thread_id)
        if plan is None:
            return None
        return build_interrupt(plan).model_dump(mode="json")

    async def handle_decision(
        self, user_id: int, thread_id: UUID, decision: dict
    ) -> AsyncGenerator[str, None]:
        """处理方案确认/放弃决策，返回 SSE 回复流"""
        action = decision.get("action")
        if action not in DECISION_MESSAGES:
            raise BizError("不支持的方案决策类型")
        async with self.session.begin():
            thread = await self.session.get(ChatThread, thread_id)
            if thread is None or thread.user_id != user_id:
                raise NotFoundError("会话不存在")
            plan_service = InsurancePlanService(self.session)
            plan = await plan_service.decide_latest_pending(
                thread_id, "approved" if action == "approve" else "rejected"
            )
            if plan is None:
                raise BizError("当前没有待确认的方案")
            await ChatMessageRepository(self.session).add(
                ChatMessage(thread_id=thread_id, role="user", content=DECISION_MESSAGES[action])
            )
        return self._decision_stream(thread_id, action)

    async def _decision_stream(self, thread_id: UUID, action: str) -> AsyncGenerator[str, None]:
        reply = DECISION_REPLIES[action]
        # 按固定长度切片推送，模拟逐字输出
        step = 6
        for i in range(0, len(reply), step):
            yield _sse("message", reply[i:i + step])
            await asyncio.sleep(0.03)
        async with AsyncSessionFactory() as session, session.begin():
            session.add(
                ChatMessage(thread_id=thread_id, role="assistant", content=reply)
            )
        yield _sse("done", {})

    async def prepare_ask(
        self, user_id: int, thread_id: UUID, content: str
    ) -> list[ChatMessage]:
        """提问前置：校验会话归属、保存用户消息，返回用于上下文的历史消息"""
        async with self.session.begin():
            thread = await self.session.get(ChatThread, thread_id)
            if thread is None or thread.user_id != user_id:
                raise NotFoundError("会话不存在")
            history = list(await ChatMessageRepository(self.session).find_by_thread(thread_id))
            await ChatMessageRepository(self.session).add(
                ChatMessage(thread_id=thread_id, role="user", content=content)
            )
        # 只保留最近 N 条作为模型上下文
        return history[-HISTORY_WINDOW:]

    # ---------- 流式生成（内部类型化事件） ----------
    # 事件序列：delta* -> answer -> references?(有来源时) -> done
    # 失败时：delta* -> answer(部分内容) -> error

    def build_stream(
        self, thread_id: UUID, history: list[ChatMessage], content: str
    ) -> AsyncGenerator[str, None]:
        """内部 SSE 流：event: delta/references/done"""
        return self._format_internal(self._stream(thread_id, history, content), thread_id)

    def build_frontend_stream(
        self, thread_id: UUID, history: list[ChatMessage], content: str
    ) -> AsyncGenerator[str, None]:
        """前端 SSE 流：event: message/additional_info（与前端契约对齐）"""
        return self._format_frontend(self._stream(thread_id, history, content), thread_id)

    async def _format_internal(
        self, events: AsyncGenerator[tuple[str, dict], None], thread_id: UUID
    ) -> AsyncGenerator[str, None]:
        async for event, data in events:
            if event == "answer":
                await self._save_assistant_message(thread_id, data["content"])
                continue
            if event == "references":
                data = {
                    # 图路径给 payload dict，legacy 路径给 ORM：统一为通用 payload 结构
                    "products": [
                        p if isinstance(p, dict) else _product_item(p)
                        for p in data["products"]
                    ],
                    "kb": data.get("kb", []),
                }
            yield _sse(event, data)

    async def _format_frontend(
        self, events: AsyncGenerator[tuple[str, dict], None], thread_id: UUID
    ) -> AsyncGenerator[str, None]:
        answer_parts: list[str] = []
        info_payload: list | None = None
        async for event, data in events:
            if event == "delta":
                answer_parts.append(data["content"])
                # 前端 parseSseMessage 会 JSON.parse 后取字符串，必须 JSON 编码
                yield _sse("message", data["content"])
            elif event == "answer":
                continue  # 持久化推迟到 references 处理完（可能追加来源后缀）
            elif event == "references":
                mentioned: list = data["products"]
                # 前端 normalizeAdditionalInfo 按扁平产品数组解析
                info_payload = [
                    {
                        **(p if isinstance(p, dict) else _product_item(p)),
                        "plan_id": None,
                        "status": "uninsured",
                    }
                    for p in mentioned
                ]
                # 实际推荐产品时生成方案（含单产品推荐），等待用户确认
                plan_interrupt = None
                if mentioned:
                    created = await self._create_plan(thread_id, mentioned)
                    if created:
                        # id 需替换为方案产品项 UUID（前端作为 item_id 传给投保流程）
                        for item in info_payload:
                            item["plan_id"] = created["plan_id"]
                            item["id"] = created["item_ids"].get(item["product_id"], item["id"])
                        plan_interrupt = created["interrupt"]
                if info_payload:
                    yield _sse("additional_info", info_payload)
                if plan_interrupt:
                    yield _sse("interrupt", plan_interrupt)
                # 条款引用来源（去重后逐行列出）
                kb_refs = data.get("kb") or []
                if kb_refs:
                    seen: set[tuple[str, str]] = set()
                    lines = []
                    for ref in kb_refs:
                        source = ref.get("product_name") or ref.get("source_name") or "未知文档"
                        heading = ref.get("heading") or "未标注章节"
                        key = (source, heading)
                        if key in seen:
                            continue
                        seen.add(key)
                        lines.append(f"- {source}（{heading}，第 {ref.get('page_no', 1)} 页）")
                    if lines:
                        suffix = "\n\n---\n**参考条款：**\n" + "\n".join(lines)
                        answer_parts.append(suffix)
                        yield _sse("message", suffix)
            elif event == "error":
                yield _sse("message", "\n\n（回答生成失败，请稍后重试）")
        await self._save_assistant_message(
            thread_id, "".join(answer_parts), additional_info=info_payload
        )

    async def _create_plan(self, thread_id: UUID, mentioned: list) -> dict | None:
        """生成待确认方案（独立短事务），session 关闭前构建好 payload，失败时降级为不发送 interrupt

        mentioned 元素为 payload dict（图路径）或 ORM Product（legacy 路径），
        统一按 id 重查 ORM 后交给方案服务。
        """
        try:
            async with AsyncSessionFactory() as session, session.begin():
                thread = await session.get(ChatThread, thread_id)
                if thread is None:
                    return None
                products: list[Product] = []
                for item in mentioned:
                    pid = item["id"] if isinstance(item, dict) else item.id
                    product = await session.get(Product, pid)
                    if product is not None:
                        products.append(product)
                if not products:
                    return None
                plan = await InsurancePlanService(session).create_from_products(
                    thread.user_id, thread_id, products
                )
                # ORM 对象随 session 关闭脱管，必须在 session 内完成序列化
                interrupt = build_interrupt(plan).model_dump(mode="json")
                item_ids = {item.product_id: str(item.id) for item in plan.items}
                return {"plan_id": str(plan.id), "interrupt": interrupt, "item_ids": item_ids}
        except Exception:
            logger.exception(f"生成保障方案失败 thread_id={thread_id}")
            return None

    async def _stream(
        self, thread_id: UUID, history: list[ChatMessage], content: str
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """LangGraph Agent 图流；runtime 不可用时回退 legacy 直连路径"""
        graph = get_advisor_graph()
        if graph is None:
            async for event in self._stream_legacy(thread_id, history, content):
                yield event
            return

        # 每轮显式重置全部通道：挂 checkpointer 后未提供的通道会继承上一轮值，
        # 残留 products/kb_refs 会造成闲聊问题误带旧推荐
        payload_in = {
            "question": content,
            "history": [{"role": m.role, "content": m.content} for m in history],
            "route": "",
            "tasks": [],
            "products": [],
            "kb_refs": [],
            "context": "",
            "answer": "",
            "error": None,
        }
        config = {"configurable": {"thread_id": str(thread_id)}, "recursion_limit": 10}

        collected: list[str] = []
        updates: dict = {}
        try:
            async for mode, payload in graph.astream(
                payload_in, config, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, meta = payload
                    if (
                        meta.get("langgraph_node") == "generate"
                        and isinstance(chunk.content, str)
                        and chunk.content
                    ):
                        collected.append(chunk.content)
                        yield "delta", {"content": chunk.content}
                else:  # "updates": {node_name: 节点返回值}
                    updates.update(payload)
        except Exception as exc:
            logger.exception(f"Agent 图执行失败 thread_id={thread_id}: {exc!r}")
            yield "answer", {"content": "".join(collected)}
            yield "error", {"message": "回答生成失败，请稍后重试"}
            return

        answer = updates.get("generate", {}).get("answer") or "".join(collected)
        products = updates.get("retrieve", {}).get("products", [])
        kb_refs = updates.get("retrieve", {}).get("kb_refs", [])

        # 动态推荐：只展示回答里实际提及的产品（payload dict），按首次提及位置排序
        mentioned = filter_mentioned(products, answer)
        yield "answer", {"content": answer}
        if mentioned or kb_refs:
            yield "references", {"products": mentioned, "kb": kb_refs}
        yield "done", {}

    async def _stream_legacy(
        self, thread_id: UUID, history: list[ChatMessage], content: str
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """回退路径：手写 AsyncOpenAI 直连（Agent runtime 不可用时保持服务可用）"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": content})

        # 检索增强：条款知识库 + 产品库（各自独立容错，失败不影响主流程）
        products, kb_refs = await self._gather_references(content)
        if products or kb_refs:
            messages[0]["content"] += "\n\n" + build_context_block(products, kb_refs)

        collected: list[str] = []
        try:
            client = AsyncOpenAI(
                api_key=settings.llm.api_key,
                base_url=DEEPSEEK_BASE_URL,
            )
            stream = await client.chat.completions.create(
                model=settings.llm.chat_model,
                messages=messages,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    collected.append(delta.content)
                    yield "delta", {"content": delta.content}
        except Exception as exc:
            logger.exception(f"流式问答失败 thread_id={thread_id}: {exc!r}")
            yield "answer", {"content": "".join(collected)}
            yield "error", {"message": "回答生成失败，请稍后重试"}
            return

        # 动态推荐：只展示回答里实际提及的产品，按首次提及位置排序
        mentioned = filter_mentioned(products, "".join(collected))
        yield "answer", {"content": "".join(collected)}
        if mentioned or kb_refs:
            yield "references", {"products": mentioned, "kb": kb_refs}
        yield "done", {}

    async def _gather_references(
        self, content: str
    ) -> tuple[list[Product], list[dict]]:
        """并行检索条款知识库、费率表精确行与产品库，任一失败降级为空"""
        product_task = retrieve_products_from_db(content)
        kb_task = retrieve_kb_chunks(content)
        rate_task = retrieve_rate_table_rows(content)
        products, kb_refs, rate_refs = await asyncio.gather(
            product_task, kb_task, rate_task
        )
        # 费率表精确行优先（已裁剪到目标维度），与语义结果按 文档+页码 去重
        merged: list[dict] = list(rate_refs)
        seen: set[tuple] = {(r.get("source_name"), r.get("page_no")) for r in rate_refs}
        for ref in kb_refs:
            key = (ref.get("source_name"), ref.get("page_no"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(ref)
        return products, merged

    async def _save_assistant_message(
        self, thread_id: UUID, content: str, additional_info: list | None = None
    ) -> None:
        if not content:
            return
        # 流式响应进行中时请求级 session 不可靠，这里使用独立的短事务
        async with AsyncSessionFactory() as session, session.begin():
            session.add(
                ChatMessage(
                    thread_id=thread_id,
                    role="assistant",
                    content=content,
                    additional_info=additional_info,
                )
            )
            # 触碰会话的 updated_at，让会话列表按最近活跃排序
            await session.execute(
                update(ChatThread)
                .where(ChatThread.id == thread_id)
                .values(updated_at=func.now())
            )


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

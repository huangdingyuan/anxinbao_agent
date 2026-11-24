# -*- coding: utf-8 -*-
"""智能问答模块端到端测试：
1. 内部接口：POST /chat-threads/{id}/chat (delta/references/done)
2. 前端契约：POST /api/v1/chat (message/additional_info/interrupt)
3. 方案选择：interrupt 下发方案 -> 历史恢复 -> decision 确认 -> interrupt 清除
4. 方案查询：GET /insurance-plans/{id}
"""
import json

import httpx

from app.common.utils import create_access_token

BASE = "http://127.0.0.1:8001/api/v1"


def login_token(username: str = "demo", password: str = "123456") -> str:
    """登录获取 JWT 访问令牌（方案表外键关联 users，需使用真实存在的用户）"""
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        return r.json()["access_token"]


HEADERS = {"Authorization": f"Bearer {login_token()}"}


def parse_sse_events(lines_iter):
    events = []
    event = None
    for line in lines_iter:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event:
            events.append((event, line[6:]))
            event = None
    return events


def main():
    with httpx.Client(timeout=180) as client:
        # 1. 创建会话
        r = client.post(f"{BASE}/chat-threads", headers=HEADERS, json={"title": "智能问答测试"})
        r.raise_for_status()
        thread_id = r.json()["id"]
        print(f"[1] 会话创建成功: {thread_id}")

        # 2. 内部 SSE 接口
        with client.stream(
            "POST",
            f"{BASE}/chat-threads/{thread_id}/chat",
            headers=HEADERS,
            json={"content": "达尔文12号重大疾病保险怎么样？"},
        ) as resp:
            assert resp.status_code == 200
            events = parse_sse_events(resp.iter_lines())
        deltas = [json.loads(d)["content"] for e, d in events if e == "delta"]
        answer = "".join(deltas)
        kinds = [e for e, _ in events]
        print(f"[2] 内部接口: delta {len(deltas)} 段, "
              f"后续事件: {[k for k in kinds if k != 'delta']}")
        assert "done" in kinds and "error" not in kinds
        refs_list = [json.loads(d) for e, d in events if e == "references"]
        assert refs_list and refs_list[0]["products"], "缺少产品参考"
        last_delta_idx = max(i for i, (e, _) in enumerate(events) if e == "delta")
        refs_idx = [i for i, (e, _) in enumerate(events) if e == "references"][0]
        done_idx = [i for i, (e, _) in enumerate(events) if e == "done"][0]
        assert last_delta_idx < refs_idx < done_idx, "references 事件顺序错误"
        print(f"    references 产品: {[p['name'] for p in refs_list[0]['products']]}")

        # 3. 历史接口（ChatHistory 形状）
        r = client.get(f"{BASE}/chat-threads/{thread_id}/messages", headers=HEADERS)
        r.raise_for_status()
        history = r.json()
        assert set(history) >= {"thread_id", "messages", "interrupt"}
        msgs = history["messages"]
        assert len(msgs) == 2
        assert msgs[1]["content"] == answer, "持久化内容与流式内容不一致"
        print(f"[3] 历史接口: {len(msgs)} 条, interrupt={history['interrupt']}")

        # 4. 前端契约：POST /api/v1/chat，多产品推荐应产生 interrupt 方案
        with client.stream(
            "POST",
            f"{BASE}/chat",
            headers=HEADERS,
            json={"message": "有什么百万医疗险可以推荐"},
        ) as resp:
            assert resp.status_code == 200, resp.read()
            fe_events = parse_sse_events(resp.iter_lines())
        fe_chunks = [json.loads(d) for e, d in fe_events if e == "message"]
        fe_answer = "".join(fe_chunks)
        infos = [json.loads(d) for e, d in fe_events if e == "additional_info"]
        interrupts = [json.loads(d) for e, d in fe_events if e == "interrupt"]
        print(f"[4] 前端接口: message {len(fe_chunks)} 段, additional_info {len(infos)} 次, "
              f"interrupt {len(interrupts)} 次")
        assert fe_answer and infos, "前端流内容缺失"
        assert infos[0][0].get("name"), "additional_info 应为扁平产品数组"
        assert interrupts, "多产品推荐未生成方案 interrupt"
        plan = interrupts[0]["plan"]
        print(f"    方案: {plan['name']}, 产品 {len(plan['items'])} 款: "
              f"{[i['name'] for i in plan['items']]}")
        assert len(plan["items"]) >= 2
        assert interrupts[0]["confirm_info"] and set(interrupts[0]["action"]) == {"approve", "reject"}

        # 5. 方案详情接口
        r = client.get(f"{BASE}/insurance-plans/{plan['id']}", headers=HEADERS)
        r.raise_for_status()
        plan_detail = r.json()
        assert plan_detail["id"] == plan["id"] and plan_detail["items"]
        print(f"[5] 方案详情: status={plan_detail['status']}, "
              f"items={[(i['name'], i['status']) for i in plan_detail['items']]}")

        # 6. 找到自动创建的会话，验证历史 interrupt 恢复
        r = client.get(f"{BASE}/chat-threads", headers=HEADERS)
        new_thread = r.json()[0]  # 按更新时间倒序
        r = client.get(f"{BASE}/chat-threads/{new_thread['id']}/messages", headers=HEADERS)
        history2 = r.json()
        assert history2["interrupt"] and history2["interrupt"]["plan"]["id"] == plan["id"], \
            "历史接口未恢复待确认方案"
        assert len(history2["messages"][1]["content"]) > 50, "助手回答内容异常"
        fe_thread_id = new_thread["id"]
        print(f"[6] 历史恢复: interrupt.plan.id={history2['interrupt']['plan']['id']}")

        # 7. 决策：确认方案
        with client.stream(
            "POST",
            f"{BASE}/chat",
            headers=HEADERS,
            json={"thread_id": fe_thread_id, "decision": {"action": "approve"}},
        ) as resp:
            assert resp.status_code == 200, resp.read()
            dec_events = parse_sse_events(resp.iter_lines())
        dec_chunks = [json.loads(d) for e, d in dec_events if e == "message"]
        print(f"[7] 确认方案: {len(dec_chunks)} 段回复: {''.join(dec_chunks)[:50]}...")
        assert "".join(dec_chunks).startswith("好的"), "确认回复内容异常"
        assert any(e == "done" for e, _ in dec_events)

        # 8. 决策后历史 interrupt 应清除，消息持久化 4 条
        r = client.get(f"{BASE}/chat-threads/{fe_thread_id}/messages", headers=HEADERS)
        history3 = r.json()
        assert history3["interrupt"] is None, "确认后 interrupt 未清除"
        roles = [m["role"] for m in history3["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"], roles
        assert history3["messages"][2]["content"] == "确认保存保险方案"
        print(f"[8] 决策后历史: interrupt=None, 消息 {len(history3['messages'])} 条")

        # 9. 重复决策应报错（无待确认方案）
        r = client.post(f"{BASE}/chat", headers=HEADERS,
                        json={"thread_id": fe_thread_id, "decision": {"action": "approve"}})
        print(f"[9] 重复决策: {r.status_code} {r.json()}")
        assert r.status_code == 400

        # 10. 越权查询方案 -> 404（签一个不存在用户的合法 token）
        r = client.get(f"{BASE}/insurance-plans/{plan['id']}",
                       headers={"Authorization": f"Bearer {create_access_token(9999)}"})
        assert r.status_code == 404

        print("\n全部通过 ✅")


if __name__ == "__main__":
    main()

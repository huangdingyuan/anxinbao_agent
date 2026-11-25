# -*- coding: utf-8 -*-
"""费率咨询回归：LangGraph Agent 路径下费率表精确行必须命中并算出具体保费

用法（后端已启动、知识库已入库）：
    .venv\\Scripts\\python.exe scripts/test_rate_consult.py
"""
import json

import httpx

from app.common.utils import create_access_token  # noqa: E402  复用项目内 JWT 签发

BASE = "http://127.0.0.1:8001/api/v1"

QUESTION = "30岁男性 30万保额 保至70岁 20年交 达尔文12号一年多少钱"


def login_token(username: str = "demo", password: str = "123456") -> str:
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        return r.json()["access_token"]


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
    headers = {"Authorization": f"Bearer {login_token()}"}
    with httpx.Client(timeout=180, headers=headers) as client:
        r = client.post(f"{BASE}/chat-threads", json={"title": "费率咨询测试"})
        r.raise_for_status()
        thread_id = r.json()["id"]
        print(f"[1] 会话创建: {thread_id}")

        with client.stream(
            "POST", f"{BASE}/chat-threads/{thread_id}/chat", json={"content": QUESTION}
        ) as resp:
            assert resp.status_code == 200, resp.read()
            events = parse_sse_events(resp.iter_lines())
        kinds = [e for e, _ in events]
        assert "error" not in kinds, "问答流出现 error 事件"
        assert "done" in kinds
        answer = "".join(json.loads(d)["content"] for e, d in events if e == "delta")
        print(f"[2] 回答（{len(answer)} 字）: {answer[:120]}...")

        refs_list = [json.loads(d) for e, d in events if e == "references"]
        assert refs_list, "缺少 references 事件"
        kb = refs_list[0].get("kb") or []
        rate_refs = [
            ref for ref in kb
            if ref.get("category") == "rate_table" and "| 男 | 20年交 | 30 |" in ref.get("content", "")
        ]
        assert rate_refs, f"费率表精确行未命中，kb 分类: {[r.get('category') for r in kb]}"
        print(f"[3] 费率行命中: {rate_refs[0].get('source_name')} 含目标指纹行")

        assert any(ch.isdigit() for ch in answer), "回答未给出具体保费数值"
        assert "没有对应数据" not in answer, "回答错误声称没有数据"
        print("[4] 回答含具体保费数值且未推脱 ✅")

        # 多轮：同线程换性别重问（带全维度才能命中精确行），route 应仍走 rate
        with client.stream(
            "POST", f"{BASE}/chat-threads/{thread_id}/chat",
            json={"content": "那30岁女性 30万保额 保至70岁 20年交 一年多少钱"},
        ) as resp:
            assert resp.status_code == 200, resp.read()
            events2 = parse_sse_events(resp.iter_lines())
        kinds2 = [e for e, _ in events2]
        assert "done" in kinds2 and "error" not in kinds2
        refs2 = [json.loads(d) for e, d in events2 if e == "references"]
        kb2 = refs2[0].get("kb") if refs2 else []
        assert kb2, "追问女性未命中费率表"
        print("[5] 多轮追问命中费率引用 ✅")

        print("\n费率咨询全部通过 ✅")


if __name__ == "__main__":
    main()

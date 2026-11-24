"""保单中心模块 e2e 测试：到期倒计时 / 保障权益解析 / 越权与不存在场景"""

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

from app.common.utils import create_access_token

BASE = "http://127.0.0.1:8001/api/v1"


def login_token(username: str = "demo", password: str = "123456") -> str:
    """登录获取 JWT 访问令牌"""
    request = urllib.request.Request(
        f"{BASE}/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}).encode("utf-8"),
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


TOKEN = login_token()
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def call(method: str, path: str, headers: dict | None = None):
    request = urllib.request.Request(BASE + path, method=method, headers=headers or {})
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    # 1. 保单列表：应有倒计时字段
    policies = call("GET", "/policies", headers=AUTH)
    assert policies, "用户 1 应有保单"
    assert all("days_to_expire" in p for p in policies), "保单应包含 days_to_expire 字段"
    active = [p for p in policies if p["status"] == "active"]
    assert all(
        isinstance(p["days_to_expire"], int) for p in active if p["expires_at"]
    ), "生效中且有到期日的保单应有倒计时"
    expired = [p for p in policies if p["status"] == "expired"]
    assert all(
        p["days_to_expire"] is not None and p["days_to_expire"] < 0 for p in expired if p["expires_at"]
    ), "已到期保单倒计时应为负数"
    print(f"[1] 保单列表：{len(policies)} 份（生效中 {len(active)} / 已到期 {len(expired)}），倒计时字段正常")

    # 2. 保障权益解析：条款知识库应能匹配并提取关键章节
    #    选取"产品名与条款文档 product_name 互相包含"的保单（与后端匹配规则一致），
    #    避免 e2e 新建保单的产品（无对应条款文档）干扰选择
    kb_names = [
        d["product_name"]
        for d in call("GET", "/knowledge/documents?category=kb")
        if d["parse_status"] == "parsed" and d["product_name"]
    ]

    def has_clause_doc(policy: dict) -> bool:
        name = (policy["product"]["name"] or "").strip()
        return bool(name) and any(name in n or n in name for n in kb_names)

    target = next(p for p in active if p["expires_at"] and has_clause_doc(p))
    benefits = call("GET", f"/policies/{target['id']}/benefits", headers=AUTH)
    assert benefits["policy_id"] == target["id"]
    assert benefits["document_name"], "应匹配到条款文档"
    assert benefits["benefits"], "应至少提取到一个权益章节"
    sections = [b["section"] for b in benefits["benefits"]]
    assert "保险责任" in sections, "应包含保险责任章节"
    assert all(b["content"].strip() for b in benefits["benefits"]), "章节内容不应为空"
    print(f"[2] 权益解析：{target['product']['name']} -> {benefits['document_name']}，章节 {sections}")

    # 3. 越权访问应 404
    try:
        call("GET", f"/policies/{target['id']}/benefits", headers={"Authorization": f"Bearer {create_access_token(999)}"})
        raise AssertionError("越权访问应被拦截")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404, f"越权应返回 404，实际 {exc.code}"
    print("[3] 越权访问被正确拦截（404）")

    # 4. 不存在的保单应 404
    try:
        call("GET", "/policies/00000000-0000-0000-0000-000000000000/benefits", headers=AUTH)
        raise AssertionError("不存在的保单应返回 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404, f"不存在应返回 404，实际 {exc.code}"
    print("[4] 不存在的保单返回 404")

    print("\n保单中心模块 e2e 全部通过 ✅")


if __name__ == "__main__":
    main()

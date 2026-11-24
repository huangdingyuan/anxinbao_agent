"""保单模块 e2e：投保成功自动生成保单 → 列表/详情/防重复/越权"""
import json
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import uuid

from app.common.database import AsyncSessionFactory
from app.modules.conversation.models import ChatThread
from app.modules.insurance_plan.service import InsurancePlanService
from app.modules.products.models import Product

BASE = "http://127.0.0.1:8001/api/v1"

async def make_plan() -> tuple[str, list[str]]:
    """创建一个含 2 个产品项的方案，返回 (plan_id, [item_id,...])"""
    async with AsyncSessionFactory() as session, session.begin():
        thread = ChatThread(user_id=1, title="保单e2e")
        session.add(thread)
        await session.flush()
        from sqlalchemy import select
        products = (await session.execute(select(Product).limit(2))).scalars().all()
        plan = await InsurancePlanService(session).create_from_products(1, thread.id, list(products))
        return str(plan.id), [str(i.id) for i in plan.items]

def request(method: str, path: str, user_id: int = 1, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"Content-Type": "application/json", "x-user-id": str(user_id)},
        data=json.dumps(body).encode() if body else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

async def main():
    plan_id, item_ids = await make_plan()
    print(f"[1] 测试方案创建成功: plan={plan_id}, items={item_ids}")

    status, before = request("GET", "/policies")
    assert status == 200, f"保单列表失败: {status}"
    print(f"[2] 保单列表: {len(before)} 张（基线）")

    # 投保第一个产品项
    status, payload = request("PATCH", f"/insurance-plans/{plan_id}/items/{item_ids[0]}/insured")
    assert status == 200, f"投保失败: {status} {payload}"
    target_item = next(i for i in payload["items"] if i["id"] == item_ids[0])
    assert target_item["status"] == "insured", target_item
    assert payload["status"] == "applying", f"方案状态应为 applying: {payload['status']}"
    print(f"[3] 投保成功: item status=insured, plan status={payload['status']}")

    status, policies = request("GET", "/policies")
    assert status == 200
    new_policies = [p for p in policies if p.get("plan_id") == plan_id]
    assert len(new_policies) == 1, f"应生成 1 张保单: {len(new_policies)}"
    policy = new_policies[0]
    assert policy["item_id"] == item_ids[0]
    assert policy["status"] == "active" and policy["policy_number"]
    assert policy["product"]["name"] and policy["premium_amount"] is not None
    print(f"[4] 保单已生成: {policy['policy_number']} 产品={policy['product']['name']} 保费={policy['premium_amount']}")

    # 保单详情
    status, detail = request("GET", f"/policies/{policy['id']}")
    assert status == 200 and detail["id"] == policy["id"] and detail["product"]["name"]
    print(f"[5] 保单详情: 状态={detail['status']} 生效={detail['effective_at']} 到期={detail['expires_at']}")

    # 重复投保同一产品项 → 不重复生成保单
    request("PATCH", f"/insurance-plans/{plan_id}/items/{item_ids[0]}/insured")
    status, policies2 = request("GET", "/policies")
    count2 = len([p for p in policies2 if p.get("plan_id") == plan_id])
    assert count2 == 1, f"重复投保不应重复生成保单: {count2}"
    print("[6] 重复投保防重: 保单数仍为 1")

    # 投保第二个产品项 → 方案状态 insured
    status, payload = request("PATCH", f"/insurance-plans/{plan_id}/items/{item_ids[1]}/insured")
    assert status == 200 and payload["status"] == "insured", payload["status"]
    status, policies3 = request("GET", "/policies")
    assert len([p for p in policies3 if p.get("plan_id") == plan_id]) == 2
    print(f"[7] 全部投保完成: plan status={payload['status']}, 保单 2 张")

    # 越权访问 → 404
    status, _ = request("GET", f"/policies/{policy['id']}", user_id=2)
    assert status == 404, f"越权应 404: {status}"
    status, _ = request("GET", "/policies", user_id=2)
    assert status == 200, status
    assert all(p.get("plan_id") != plan_id for p in _), "其他用户不应看到该方案保单"
    print("[8] 越权校验: 其他用户 404 / 列表隔离")

    print("\n全部通过 ✅")

if __name__ == "__main__":
    asyncio.run(main())

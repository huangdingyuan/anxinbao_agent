"""理赔模块 e2e：提交申请 → 列表/详情 → 状态流转 → 非法流转/到期保单/金额校验"""
import json
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8001/api/v1"


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


def main():
    # 取一张生效中的保单与一张到期保单（demo 数据）
    status, policies = request("GET", "/policies")
    assert status == 200, f"保单列表失败: {status}"
    active = next((p for p in policies if p["status"] == "active"), None)
    expired = next((p for p in policies if p["status"] == "expired"), None)
    assert active is not None, "缺少生效中保单，请先完成投保流程"
    print(f"[1] 候选保单: active={active['policy_number']} expired={expired['policy_number'] if expired else '无'}")

    status, before = request("GET", "/claims")
    assert status == 200, status
    print(f"[2] 理赔列表基线: {len(before)} 条")

    # 提交理赔申请
    status, claim = request("POST", "/claims", body={
        "policy_id": active["id"],
        "claim_type": "medical",
        "amount": "5000.00",
        "description": "住院医疗费用报销，共 5 天",
    })
    assert status == 200, f"提交理赔失败: {status} {claim}"
    assert claim["status"] == "submitted" and claim["claim_number"]
    assert claim["policy"]["policy_number"] == active["policy_number"]
    assert claim["policy"]["product_name"], claim["policy"]
    claim_id = claim["id"]
    print(f"[3] 理赔已提交: {claim['claim_number']} 金额={claim['amount']} 保单={claim['policy']['policy_number']}")

    # 列表与详情
    status, claims = request("GET", "/claims")
    assert status == 200 and any(c["id"] == claim_id for c in claims), "列表应包含新理赔"
    status, detail = request("GET", f"/claims/{claim_id}")
    assert status == 200 and detail["claim_number"] == claim["claim_number"]
    # 按保单过滤
    status, filtered = request("GET", f"/claims?policy_id={active['id']}")
    assert status == 200 and all(c["policy"]["id"] == active["id"] for c in filtered)
    print(f"[4] 列表/详情/按保单过滤: 共 {len(claims)} 条，过滤后 {len(filtered)} 条")

    # 状态流转：submitted -> reviewing -> approved -> paid
    for step, expect in enumerate(["reviewing", "approved", "paid"], start=5):
        status, updated = request("PATCH", f"/claims/{claim_id}/status", body={"status": expect})
        assert status == 200 and updated["status"] == expect, f"流转到 {expect} 失败: {status} {updated}"
        print(f"[{step}] 状态流转 -> {expect}")

    # 非法流转：paid 是终态
    status, err = request("PATCH", f"/claims/{claim_id}/status", body={"status": "reviewing"})
    assert status == 400, f"终态再流转应 400: {status} {err}"
    print("[8] 终态校验: paid 不可再流转")

    # 到期保单不可理赔
    if expired:
        status, err = request("POST", "/claims", body={
            "policy_id": expired["id"],
            "claim_type": "accident",
        })
        assert status == 400, f"到期保单理赔应 400: {status} {err}"
        print("[9] 到期保单校验: 状态=expired 不可发起理赔")

    # 金额必须大于 0
    status, err = request("POST", "/claims", body={
        "policy_id": active["id"], "claim_type": "medical", "amount": "-100",
    })
    assert status == 400, f"负数金额应 400: {status} {err}"
    print("[10] 金额校验: 负数金额被拒绝")

    # 越权访问 → 404
    status, _ = request("GET", f"/claims/{claim_id}", user_id=2)
    assert status == 404, f"越权应 404: {status}"
    # 不存在的保单提交理赔 → 404
    status, _ = request("POST", "/claims", body={
        "policy_id": "00000000-0000-0000-0000-000000000000", "claim_type": "medical",
    })
    assert status == 404, f"不存在的保单应 404: {status}"
    print("[11] 归属/存在性校验: 越权 404 / 未知保单 404")

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()

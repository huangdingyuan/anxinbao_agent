"""用户模块 e2e 测试：GET/PATCH /api/v1/users/me"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001/api/v1"


def call(method: str, path: str, user_id: int = 1, body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"Content-Type": "application/json", "x-user-id": str(user_id)},
        data=json.dumps(body).encode("utf-8") if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8")) or {}
            return response.status, payload
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read().decode("utf-8")) or {}
        return error.code, payload


def check(name: str, condition: bool, detail: object = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {detail if not condition else ''}")
    assert condition, name


def main() -> None:
    # 1. 查询资料
    status, profile = call("GET", "/users/me")
    check("GET /users/me 200", status == 200, (status, profile))
    check("资料包含 username/email/display_name", profile.get("username") == "demo" and bool(profile.get("email")))
    print("当前资料:", profile)

    # 2. 编辑资料
    status, updated = call("PATCH", "/users/me", body={
        "display_name": "演示用户",
        "phone": "13800001111",
    })
    check("PATCH /users/me 200", status == 200, (status, updated))
    check("昵称与手机号已更新", updated.get("display_name") == "演示用户" and updated.get("phone") == "13800001111")

    # 3. 编辑邮箱（改成原值再改成新值再改回）
    new_email = "demo2@example.com"
    status, updated = call("PATCH", "/users/me", body={"email": new_email})
    check("PATCH email 200", status == 200, (status, updated))
    check("邮箱已更新", updated.get("email") == new_email)
    status, updated = call("PATCH", "/users/me", body={"email": "demo@example.com"})
    check("恢复邮箱 200", status == 200 and updated.get("email") == "demo@example.com")

    # 4. 错误场景
    status, error = call("GET", "/users/me", user_id=999)
    check("不存在用户 404", status == 404, (status, error))

    status, error = call("PATCH", "/users/me", body={})
    check("空 payload 400", status == 400, (status, error))

    status, error = call("PATCH", "/users/me", body={"email": "not-an-email"})
    check("非法邮箱 422", status == 422, (status, error))

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()

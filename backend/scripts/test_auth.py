"""认证模块 e2e 测试：POST /api/v1/auth/login"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001/api/v1"


def call_login(body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE}/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode("utf-8"),
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
    # 1. 正确账号密码
    status, payload = call_login({"username": "demo", "password": "123456"})
    check("正确密码登录 200", status == 200, (status, payload))
    check("返回用户资料", payload.get("id") == 1 and payload.get("username") == "demo")
    check("不泄露 password_hash", "password_hash" not in payload)
    print("登录成功资料:", payload)

    # 2. 错误密码
    status, payload = call_login({"username": "demo", "password": "wrong-pass"})
    check("错误密码 401", status == 401, (status, payload))
    check("统一错误提示", payload.get("detail") == "用户名或密码错误" or payload.get("message") == "用户名或密码错误")

    # 3. 不存在的用户（与错误密码同提示，防枚举）
    status, payload = call_login({"username": "no-such-user", "password": "123456"})
    check("不存在用户 401", status == 401, (status, payload))

    # 4. 缺少字段 422
    status, payload = call_login({"username": "demo"})
    check("缺密码字段 422", status == 422, (status, payload))

    # 5. 空 payload 422
    status, payload = call_login({})
    check("空 payload 422", status == 422, (status, payload))

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()

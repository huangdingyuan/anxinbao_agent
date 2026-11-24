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


def call_with_auth(path: str, token: str | None = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(f"{BASE}{path}", method="GET", headers=headers)
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
    # 1. 正确账号密码：返回 JWT 访问令牌 + 用户资料
    status, payload = call_login({"username": "demo", "password": "123456"})
    check("正确密码登录 200", status == 200, (status, payload))
    check("登录返回 access_token", isinstance(payload.get("access_token"), str) and payload.get("token_type") == "bearer")
    user = payload.get("user") or {}
    check("返回用户资料", user.get("id") == 1 and user.get("username") == "demo")
    check("不泄露 password_hash", "password_hash" not in payload and "password_hash" not in user)
    token = payload.get("access_token")
    print("登录成功:", {k: v for k, v in payload.items() if k != "access_token"})

    # 2. 携带令牌访问受保护接口
    status, profile = call_with_auth("/users/me", token)
    check("携带 Bearer 令牌访问 /users/me 200", status == 200 and profile.get("username") == "demo", (status, profile))

    # 3. 无 Authorization 头访问受保护接口 → 401
    status, body = call_with_auth("/users/me")
    check("无 Authorization 头 401", status == 401, (status, body))

    # 4. 伪造 token → 401
    status, body = call_with_auth("/users/me", "header.payload.forged-signature")
    check("伪造 token 401", status == 401, (status, body))

    # 5. 错误密码
    status, payload = call_login({"username": "demo", "password": "wrong-pass"})
    check("错误密码 401", status == 401, (status, payload))
    check("统一错误提示", payload.get("detail") == "用户名或密码错误" or payload.get("message") == "用户名或密码错误")

    # 6. 不存在的用户（与错误密码同提示，防枚举）
    status, payload = call_login({"username": "no-such-user", "password": "123456"})
    check("不存在用户 401", status == 401, (status, payload))

    # 7. 缺少字段 422
    status, payload = call_login({"username": "demo"})
    check("缺密码字段 422", status == 422, (status, payload))

    # 8. 空 payload 422
    status, payload = call_login({})
    check("空 payload 422", status == 422, (status, payload))

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()

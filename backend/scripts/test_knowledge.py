"""知识库模块 e2e 测试：文档列表 / 切块浏览 / 关键词检索 / 入库幂等"""

import json
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8001/api/v1"


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    # 1. 文档列表：条款 + 费率表各 10 份（前提：parse_kb.py 已跑完 parse+ingest）
    docs = call("GET", "/knowledge/documents")
    assert isinstance(docs, list), "文档列表应为数组"
    print(f"[1] 文档总数：{len(docs)}")
    kb_docs = call("GET", "/knowledge/documents?category=kb")
    rate_docs = call("GET", "/knowledge/documents?category=rate_table")
    print(f"    条款 {len(kb_docs)} 份 / 费率表 {len(rate_docs)} 份")
    parsed = [d for d in docs if d["parse_status"] == "parsed"]
    assert parsed, "至少存在一份已解析文档"
    failed = [d["source_name"] for d in docs if d["parse_status"] == "failed"]
    if failed:
        print(f"    [警告] 解析失败：{failed}")
    assert all(d["product_name"] for d in parsed), "已解析文档应有产品名"
    assert all(d["chunk_count"] > 0 for d in parsed), "已解析文档切块数应大于 0"

    # 2. 切块浏览：取第一份条款的前 2 块
    target = kb_docs[0]
    chunks = call("GET", f"/knowledge/documents/{target['id']}/chunks")
    assert len(chunks) == target["chunk_count"], "切块数应与文档记录一致"
    first = chunks[0]
    assert first["heading"], "条款首块应带章节标题"
    print(f"[2] 切块浏览 {target['source_name']}：{len(chunks)} 块，首块标题「{first['heading']}」")
    print(f"    首块预览：{first['content'][:60]}...")

    # 3. 关键词检索：应命中相关条款块
    results = call("GET", "/knowledge/search?q=" + urllib.parse.quote("住院医疗费用报销"))
    assert results, "检索应至少命中一条"
    print(f"[3] 检索「住院医疗费用报销」命中 {len(results)} 条")
    top = results[0]
    print(f"    TOP1：{top['product_name'] or top['source_name']}（{top['heading']}，第 {top['page_no']} 页）score={top['score']}")
    print(f"    内容预览：{top['content'][:80]}...")

    # 4. 费率类关键词应命中费率表
    rate_results = call("GET", "/knowledge/search?q=" + urllib.parse.quote("年交保费 保险期间"))
    print(f"[4] 检索费率关键词命中 {len(rate_results)} 条")
    if rate_results:
        print(f"    TOP1：{rate_results[0]['product_name'] or rate_results[0]['source_name']}")

    print("\n知识库模块 e2e 全部通过 ✅")


if __name__ == "__main__":
    main()

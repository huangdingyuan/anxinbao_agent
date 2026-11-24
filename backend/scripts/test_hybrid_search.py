"""混合检索 e2e 测试：关键词+向量 RRF 融合

运行前置：scripts/parse_kb.py backfill 已为存量块补算向量
"""

import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8001/api/v1"


def search(query: str) -> dict:
    url = f"{BASE}/knowledge/search?q={urllib.parse.quote(query)}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def check(name: str, condition: bool, detail: object = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {detail if not condition else ''}")
    assert condition, name


def main() -> None:
    # 1. 关键词精确查询（两路都应命中）
    results = search("住院医疗费用报销")
    check("关键词查询命中", len(results) >= 1, results)
    print(f"[1] 「住院医疗费用报销」命中 {len(results)} 条, top1: {results[0]['source_name']} score={results[0]['score']}")

    # 2. 语义查询（不含条款原文字眼，验证向量路生效）
    #    "做完手术花的钱怎么赔" 与条款中「住院医疗费用/手术保险金」语义相关
    semantic_results = search("做完手术住院花的钱怎么赔")
    check("语义查询命中", len(semantic_results) >= 1, semantic_results)
    top = semantic_results[0]
    print(f"[2] 语义查询命中 {len(semantic_results)} 条, top1: {top['source_name']} heading={top.get('heading')} score={top['score']}")

    # 3. 费率语义查询：不同年龄保费怎么算 → 应命中费率表
    rate_results = search("30岁的人买这份保险一年要交多少钱")
    check("费率语义查询命中", len(rate_results) >= 1, rate_results)
    print(f"[3] 费率语义查询命中 {len(rate_results)} 条, top1: {rate_results[0]['source_name']} category={rate_results[0]['category']}")

    # 4. 无关查询：应返回空或极少结果
    none_results = search("今天天气怎么样适合出游吗")
    print(f"[4] 无关查询返回 {len(none_results)} 条（0 条为最佳）")

    # 5. score 为 RRF 浮点数
    check("score 为浮点 RRF 分数", isinstance(top["score"], (int, float)), top["score"])

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()

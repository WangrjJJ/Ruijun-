#!/usr/bin/env python3
"""
JARVIS Search — Obsidian vault语义搜索
加载向量索引，对查询文本做余弦相似度匹配。

用法:
  python3 search.py "采购优化MILP"
  python3 search.py "数字化转型" --type "重点行动计划" --top_k 3
  python3 search.py "BTC策略" --tag "投资"
  python3 search.py "精益生产" --format detail
"""

import os
import sys
import json
import sqlite3
import argparse
import numpy as np
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "jarvis.db")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_index():
    """加载向量索引，返回 (embeddings, metadata, chunks)"""
    emb_path = os.path.join(DATA_DIR, "embeddings.npy")
    meta_path = os.path.join(DATA_DIR, "metadata.json")
    chunk_path = os.path.join(DATA_DIR, "chunks.json")

    if not all(os.path.exists(p) for p in [emb_path, meta_path, chunk_path]):
        print("索引不存在，请先运行: python3 indexer.py", file=sys.stderr)
        sys.exit(1)

    embeddings = np.load(emb_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    with open(chunk_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    return embeddings, metadata, chunks


def embed_query(text: str, config: dict, retries=3) -> np.ndarray:
    """嵌入单条查询文本（含重试）"""
    import time
    for attempt in range(retries):
        try:
            r = requests.post(
                f"{config['api_base']}/embeddings",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["embedding_model"],
                    "input": text[:3000],
                },
                timeout=30,
            )
            r.raise_for_status()
            return np.array(r.json()["data"][0]["embedding"], dtype=np.float32)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                raise


def cosine_similarity(a: np.ndarray, B: np.ndarray) -> np.ndarray:
    """计算向量a与矩阵B每行的余弦相似度"""
    norm_a = np.linalg.norm(a)
    norm_B = np.linalg.norm(B, axis=1)
    # 避免除零
    norm_B = np.where(norm_B == 0, 1e-10, norm_B)
    return B @ a / (norm_B * norm_a)


def search(query: str, top_k: int = 5, type_filter: str = None,
           tag_filter: str = None, fmt: str = "brief") -> list:
    """语义搜索主函数"""
    config = load_config()
    embeddings, metadata, chunks = load_index()

    # 嵌入查询
    q_emb = embed_query(query, config)

    # 余弦相似度
    scores = cosine_similarity(q_emb, embeddings)

    # 构建结果（带过滤）
    results = []
    for i in range(len(scores)):
        meta = metadata[i]

        # type过滤
        if type_filter and meta.get("type", "") != type_filter:
            continue

        # tag过滤
        if tag_filter:
            tags = meta.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            if not any(tag_filter.lower() in t.lower() for t in tags):
                continue

        results.append({
            "idx": i,
            "score": float(scores[i]),
            "path": meta.get("path", ""),
            "title": meta.get("title", ""),
            "type": meta.get("type", ""),
            "tags": meta.get("tags", []),
            "section": meta.get("section", ""),
            "snippet": chunks[i][:200] if fmt == "brief" else chunks[i],
        })

    # 排序取top_k
    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:top_k]

    # 添加排名
    for rank, r in enumerate(results, 1):
        r["rank"] = rank
        r["score"] = round(r["score"], 4)
        del r["idx"]

    return results


def search_decisions(query, top_k=5):
    """在决策日志中搜索（LIKE关键词匹配）"""
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    pattern = f"%{query}%"
    rows = conn.execute(
        """SELECT id, domain, title, context, chosen, rationale, tags,
                  confidence, status, created_at
           FROM decisions
           WHERE title LIKE ? OR context LIKE ? OR rationale LIKE ? OR tags LIKE ?
           ORDER BY created_at DESC LIMIT ?""",
        (pattern, pattern, pattern, pattern, top_k)
    ).fetchall()
    conn.close()
    results = []
    for rank, row in enumerate(rows, 1):
        results.append({
            "rank": rank,
            "source": "decision",
            "id": row["id"],
            "domain": row["domain"],
            "title": row["title"],
            "context": row["context"][:200] if row["context"] else "",
            "chosen": row["chosen"],
            "tags": row["tags"],
            "status": row["status"],
            "created_at": row["created_at"],
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="JARVIS 语义搜索")
    parser.add_argument("query", help="搜索查询文本")
    parser.add_argument("--top_k", type=int, default=5, help="返回结果数（默认5）")
    parser.add_argument("--type", dest="type_filter", help="按type过滤（如: 重点行动计划）")
    parser.add_argument("--tag", dest="tag_filter", help="按tag过滤（如: 投资）")
    parser.add_argument("--format", dest="fmt", choices=["brief", "detail"],
                        default="brief", help="输出格式")
    parser.add_argument("--source", choices=["vault", "decisions", "all"],
                        default="vault", help="搜索源（默认vault）")
    args = parser.parse_args()

    results = []
    if args.source in ("vault", "all"):
        results.extend(search(args.query, args.top_k, args.type_filter,
                              args.tag_filter, args.fmt))
    if args.source in ("decisions", "all"):
        results.extend(search_decisions(args.query, args.top_k))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

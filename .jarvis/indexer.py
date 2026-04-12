#!/usr/bin/env python3
"""
JARVIS Indexer — Obsidian vault → 向量索引
扫描vault所有.md文件，提取frontmatter+正文，按##分块，嵌入后存储。

用法:
  python3 indexer.py           # 增量更新（只处理变更文件）
  python3 indexer.py --force   # 全量重建
"""

import os
import sys
import json
import glob
import hashlib
import re
import time
import numpy as np
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

# ── 配置加载 ───────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ── Frontmatter解析 ────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple:
    """返回 (metadata_dict, body_text)"""
    meta = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            yaml_block = parts[1].strip()
            body = parts[2].strip()
            for line in yaml_block.split("\n"):
                line = line.strip()
                if ":" in line and not line.startswith("-"):
                    key, val = line.split(":", 1)
                    key = key.strip().strip('"')
                    val = val.strip().strip('"').strip("'")
                    # 处理YAML列表 [a, b, c]
                    if val.startswith("[") and val.endswith("]"):
                        val = [v.strip().strip('"').strip("'")
                               for v in val[1:-1].split(",") if v.strip()]
                    meta[key] = val
    return meta, body


# ── 分块策略 ───────────────────────────────────────────────

def chunk_by_sections(body: str, meta: dict, file_path: str,
                      max_chars=4000, min_chars=50) -> list:
    """按 ## 标题切块，返回chunk列表"""
    title = meta.get("title", os.path.splitext(os.path.basename(file_path))[0])
    doc_type = meta.get("type", "")
    doc_tags = meta.get("tags", [])
    if isinstance(doc_tags, str):
        doc_tags = [doc_tags]
    doc_date = meta.get("date", "")
    doc_status = meta.get("status", "")

    base_meta = {
        "path": file_path,
        "title": title,
        "type": doc_type,
        "tags": doc_tags,
        "date": doc_date,
        "status": doc_status,
    }

    # 按 ## 拆分
    sections = re.split(r'\n(?=## )', body)
    chunks = []

    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue

        # 提取section标题
        heading = ""
        lines = sec.split("\n", 1)
        if lines[0].startswith("## "):
            heading = lines[0].lstrip("# ").strip()
            sec_body = lines[1].strip() if len(lines) > 1 else ""
        else:
            sec_body = sec

        # 跳过过短内容
        if len(sec_body) < min_chars and not heading:
            continue

        # 超长section按段落再分
        if len(sec_body) > max_chars:
            paragraphs = re.split(r'\n\n+', sec_body)
            current = ""
            part_idx = 0
            for para in paragraphs:
                if len(current) + len(para) > max_chars and current:
                    chunks.append({
                        **base_meta,
                        "section": f"{heading} (part {part_idx+1})" if heading else f"part {part_idx+1}",
                        "text": current.strip(),
                    })
                    current = para
                    part_idx += 1
                else:
                    current = current + "\n\n" + para if current else para
            if current.strip() and len(current.strip()) >= min_chars:
                chunks.append({
                    **base_meta,
                    "section": f"{heading} (part {part_idx+1})" if part_idx > 0 else heading,
                    "text": current.strip(),
                })
        else:
            chunks.append({
                **base_meta,
                "section": heading,
                "text": sec_body if sec_body else sec,
            })

    # 如果整个文件没产生chunk（太短），把整体作为一个chunk
    if not chunks and body.strip():
        chunks.append({
            **base_meta,
            "section": "",
            "text": body.strip()[:max_chars],
        })

    return chunks


# ── Embedding API ──────────────────────────────────────────

def embed_texts(texts: list, config: dict, batch_size=32) -> list:
    """调用硅基流动API嵌入文本，返回向量列表"""
    all_embeddings = []
    total = len(texts)

    for i in range(0, total, batch_size):
        batch = texts[i:i+batch_size]
        success = False
        for attempt in range(3):
            try:
                r = requests.post(
                    f"{config['api_base']}/embeddings",
                    headers={
                        "Authorization": f"Bearer {config['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config["embedding_model"],
                        "input": batch,
                    },
                    timeout=60,
                )
                r.raise_for_status()
                data = r.json()
                batch_embs = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(batch_embs)
                print(f"  嵌入进度: {min(i+batch_size, total)}/{total}")
                success = True
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  [RETRY] batch {i} 第{attempt+1}次失败, 重试...")
                    time.sleep(2)
                else:
                    print(f"  [ERROR] 嵌入失败 (batch {i}): {e}")
                    all_embeddings.extend([[0.0] * 1024] * len(batch))
        time.sleep(0.3)  # 速率控制

    return all_embeddings


# ── 文件指纹 ───────────────────────────────────────────────

def file_hash(filepath: str) -> str:
    """文件mtime + size作为变更指纹"""
    stat = os.stat(filepath)
    return f"{stat.st_mtime:.6f}_{stat.st_size}"


# ── 主流程 ─────────────────────────────────────────────────

def build_index(force=False):
    config = load_config()
    vault_path = config["vault_path"]
    exclude_dirs = set(config.get("exclude_dirs", []))

    print(f"JARVIS Indexer v1.0")
    print(f"Vault: {vault_path}")
    print(f"Model: {config['embedding_model']}")
    print(f"Mode:  {'全量重建' if force else '增量更新'}")
    print()

    # 加载已有索引信息
    index_info_path = os.path.join(DATA_DIR, "index_info.json")
    prev_hashes = {}
    if not force and os.path.exists(index_info_path):
        with open(index_info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
            prev_hashes = info.get("file_hashes", {})

    # 扫描vault
    all_md = []
    for root, dirs, files in os.walk(vault_path):
        # 排除目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if f.endswith(".md"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, vault_path)
                all_md.append((rel, full))

    print(f"扫描到 {len(all_md)} 个.md文件")

    # 检查变更
    if not force:
        changed = []
        current_hashes = {}
        for rel, full in all_md:
            h = file_hash(full)
            current_hashes[rel] = h
            if prev_hashes.get(rel) != h:
                changed.append((rel, full))
        if not changed and prev_hashes:
            print("无文件变更，索引已是最新。")
            return
        print(f"检测到 {len(changed)} 个文件变更，全部重新索引")

    # 解析并分块
    print("\n解析与分块...")
    all_chunks = []
    current_hashes = {}
    for rel, full in all_md:
        current_hashes[rel] = file_hash(full)
        try:
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            meta, body = parse_frontmatter(content)
            chunks = chunk_by_sections(body, meta, rel)
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  [WARN] 跳过 {rel}: {e}")

    print(f"生成 {len(all_chunks)} 个chunks")

    if not all_chunks:
        print("[ERROR] 无有效chunk，退出")
        return

    # 构造嵌入输入
    embed_inputs = []
    for c in all_chunks:
        prefix = c["title"]
        if c["section"]:
            prefix += f" | {c['section']}"
        text = f"{prefix}\n{c['text']}"
        # 截断过长文本（bge-m3 max 8192 tokens，保守取前3000字符）
        embed_inputs.append(text[:3000])

    # 嵌入
    print(f"\n调用 {config['embedding_model']} 嵌入 {len(embed_inputs)} 个chunks...")
    embeddings = embed_texts(embed_inputs, config)

    # 存储
    os.makedirs(DATA_DIR, exist_ok=True)
    emb_array = np.array(embeddings, dtype=np.float32)
    np.save(os.path.join(DATA_DIR, "embeddings.npy"), emb_array)

    metadata = [{k: v for k, v in c.items() if k != "text"} for c in all_chunks]
    with open(os.path.join(DATA_DIR, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    chunk_texts = [c["text"][:500] for c in all_chunks]  # snippet用，截取前500字符
    with open(os.path.join(DATA_DIR, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(chunk_texts, f, ensure_ascii=False, indent=2)

    index_info = {
        "indexed_at": datetime.now().isoformat(),
        "total_files": len(all_md),
        "total_chunks": len(all_chunks),
        "embedding_dim": emb_array.shape[1] if emb_array.ndim == 2 else 0,
        "model": config["embedding_model"],
        "file_hashes": current_hashes,
    }
    with open(os.path.join(DATA_DIR, "index_info.json"), "w", encoding="utf-8") as f:
        json.dump(index_info, f, ensure_ascii=False, indent=2)

    print(f"\n索引完成!")
    print(f"  文件数: {len(all_md)}")
    print(f"  chunk数: {len(all_chunks)}")
    print(f"  向量维度: {emb_array.shape}")
    print(f"  存储路径: {DATA_DIR}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    build_index(force=force)

#!/usr/bin/env python3
"""
JARVIS Health Check — 系统健康检查
检查各子系统状态，输出诊断报告。

用法:
  python3 health_check.py                # 全量检查
  python3 health_check.py --json         # JSON输出
  python3 health_check.py --quick        # 快速检查（跳过API探测）
"""

import os
import sys
import json
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

sys.path.insert(0, SCRIPT_DIR)
from jarvis_common import load_config, DB_PATH


def check_disk() -> dict:
    try:
        import shutil
        usage = shutil.disk_usage(VAULT_ROOT)
        free_gb = round(usage.free / (1024**3), 1)
        total_gb = round(usage.total / (1024**3), 1)
        pct = round((1 - usage.free / usage.total) * 100, 1)
        return {"status": "OK" if free_gb > 5 else "WARN", "free_gb": free_gb,
                "total_gb": total_gb, "used_pct": pct}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)[:80]}


def check_index() -> dict:
    emb_path = os.path.join(DATA_DIR, "embeddings.npy")
    meta_path = os.path.join(DATA_DIR, "metadata.json")
    info_path = os.path.join(DATA_DIR, "index_info.json")

    if not all(os.path.exists(p) for p in [emb_path, meta_path, info_path]):
        return {"status": "MISSING", "detail": "索引文件不完整"}

    try:
        # 读 index_info（utf-8，失败用 gbk 回退）
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                with open(info_path, "r", encoding="gbk") as f:
                    info = json.load(f)
            except Exception:
                raise
        import numpy as np
        emb = np.load(emb_path)
        # 读 metadata（同编码策略）
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            with open(meta_path, "r", encoding="gbk") as f:
                meta = json.load(f)

        age_hours = (datetime.now() - datetime.fromisoformat(
            info.get("indexed_at", "2000-01-01T00:00:00"))).total_seconds() / 3600

        return {
            "status": "OK" if age_hours < 48 else "STALE",
            "files": info.get("total_files", 0),
            "chunks": info.get("total_chunks", 0),
            "dim": emb.shape[1] if emb.ndim == 2 else 0,
            "age_hours": round(age_hours, 1),
            "model": info.get("model", "?"),
        }
    except Exception as e:
        return {"status": "CORRUPT", "error": str(e)[:120]}


def check_db() -> dict:
    if not os.path.exists(DB_PATH):
        return {"status": "MISSING", "path": DB_PATH}
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        n_decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        n_open = conn.execute("SELECT COUNT(*) FROM decisions WHERE status='open'").fetchone()[0]
        n_reviews = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        n_memories = conn.execute("SELECT COUNT(*) FROM memory_kv").fetchone()[0]
        conn.close()
        return {
            "status": "OK",
            "size_kb": os.path.getsize(DB_PATH) // 1024,
            "decisions": n_decisions,
            "open_decisions": n_open,
            "reviews": n_reviews,
            "kv_memories": n_memories,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)[:120]}


def check_siliconflow(config: dict) -> dict:
    try:
        import requests
        r = requests.post(
            f"{config['api_base']}/embeddings",
            headers={"Authorization": f"Bearer {config['api_key']}"},
            json={"model": config["embedding_model"], "input": "health_check"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            dim = len(data["data"][0]["embedding"]) if data.get("data") else 0
            return {"status": "OK", "model": config["embedding_model"], "dim": dim,
                    "latency_ms": round(r.elapsed.total_seconds() * 1000)}
        return {"status": f"HTTP {r.status_code}", "detail": r.text[:120]}
    except Exception as e:
        return {"status": "DOWN", "error": str(e)[:120]}


def check_deepseek() -> dict:
    try:
        from jarvis_common import call_llm
        result = call_llm("回复OK", system="只回复OK", max_tokens=10)
        if result and "error" not in result.lower():
            return {"status": "OK", "response": result[:50]}
        return {"status": "UNEXPECTED", "response": result[:100]}
    except Exception as e:
        return {"status": "DOWN", "error": str(e)[:120]}


def check_outlook() -> dict:
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        ns = outlook.GetNamespace("MAPI")
        inbox = ns.GetDefaultFolder(6)
        count = inbox.Items.Count
        return {"status": "OK", "inbox_count": count}
    except ImportError:
        return {"status": "SKIP", "detail": "pywin32 not installed"}
    except Exception as e:
        return {"status": "DOWN", "error": str(e)[:120]}


def check_events_files() -> dict:
    result = {}
    all_ok = True
    for name in ["ingestion_events.jsonl", "email_events.jsonl"]:
        fp = os.path.join(DATA_DIR, name)
        if os.path.exists(fp):
            size_kb = os.path.getsize(fp) // 1024
            line_count = 0
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                for _ in f:
                    line_count += 1
            result[name] = {"lines": line_count, "size_kb": size_kb}
        else:
            result[name] = {"lines": 0, "size_kb": 0}
            all_ok = False
    return {"status": "OK" if all_ok else "WARN", "files": result}


def run_all(quick: bool = False) -> dict:
    config = load_config()
    result = {
        "timestamp": datetime.now().isoformat(),
        "vault": VAULT_ROOT,
        "checks": {},
    }

    result["checks"]["disk"] = check_disk()
    result["checks"]["index"] = check_index()
    result["checks"]["db"] = check_db()
    result["checks"]["events"] = check_events_files()

    if not quick:
        result["checks"]["siliconflow"] = check_siliconflow(config)
        result["checks"]["deepseek"] = check_deepseek()
        result["checks"]["outlook"] = check_outlook()
    else:
        result["checks"]["siliconflow"] = {"status": "SKIPPED"}
        result["checks"]["deepseek"] = {"status": "SKIPPED"}
        result["checks"]["outlook"] = {"status": "SKIPPED"}

    # 汇总
    all_statuses = [v.get("status", "?") for v in result["checks"].values()]
    errors = [s for s in all_statuses if s in ("DOWN", "MISSING", "CORRUPT", "ERROR")]
    warns = [s for s in all_statuses if s in ("WARN", "STALE", "UNEXPECTED", "SKIPPED")]
    ok = [s for s in all_statuses if s == "OK"]

    result["summary"] = {
        "healthy": len(errors) == 0,
        "ok": len(ok),
        "warn": len(warns),
        "error": len(errors),
        "errors_detail": {k: v for k, v in result["checks"].items()
                         if v.get("status") in ("DOWN", "MISSING", "CORRUPT", "ERROR")},
    }

    return result


def main():
    import io
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="JARVIS 健康检查")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--quick", action="store_true", help="快速模式（跳过API探测）")
    args = parser.parse_args()

    result = run_all(quick=args.quick)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=" * 50)
        print("JARVIS Health Check")
        print("=" * 50)
        for name, check in result["checks"].items():
            status = check.get("status", "?")
            icon = {"OK": "[OK]", "WARN": "[WARN]", "STALE": "[OLD]", "DOWN": "[DOWN]",
                    "MISSING": "[MISS]", "CORRUPT": "[CORRUPT]", "ERROR": "[ERR]",
                    "SKIPPED": "[SKIP]", "EMPTY": "[EMPTY]"}.get(status, "[?]")
            print(f"  {icon} {name:20s} {status}")
            if status not in ("OK", "SKIPPED", "EMPTY"):
                detail = {k: v for k, v in check.items() if k != "status"}
                if detail:
                    print(f"    {detail}")

        s = result["summary"]
        healthy_str = "HEALTHY" if s["healthy"] else "PROBLEMS DETECTED"
        print(f"\n{healthy_str}  OK:{s['ok']} WARN:{s['warn']} ERROR:{s['error']}")

        if not s["healthy"]:
            sys.exit(1)


if __name__ == "__main__":
    main()

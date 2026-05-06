#!/usr/bin/env python3
"""
JARVIS Scheduler Wrapper — Windows Task Scheduler 封装
使用 schtasks.exe 注册/管理 JARVIS 定时任务。

用法:
  python3 scheduler_wrapper.py --install     # 注册所有计划任务
  python3 scheduler_wrapper.py --uninstall   # 删除所有计划任务
  python3 scheduler_wrapper.py --list        # 列出当前任务
  python3 scheduler_wrapper.py --run daily-brief  # 手动触发日报生成
  python3 scheduler_wrapper.py --run ingest       # 手动触发摄入扫描
  python3 scheduler_wrapper.py --status      # 查看任务状态
"""

import os
import sys
import json
import argparse
import subprocess
import logging
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Python 路径
PYTHON_EXE = r"C:\Users\01455310\AppData\Local\anaconda3\python.exe"

# 任务定义
TASKS = {
    "JARVIS_IndexUpdate": {
        "schedule": "DAILY",
        "start_time": "07:00",
        "command": f'"{PYTHON_EXE}" "{os.path.join(SCRIPT_DIR, "indexer.py")}"',
        "work_dir": VAULT_ROOT,
        "description": "JARVIS vault vector index update (daily 7:00 AM)",
    },
    "JARVIS_DailyBrief": {
        "schedule": "DAILY",
        "start_time": "07:15",
        "command": (
            f'"{PYTHON_EXE}" "{os.path.join(SCRIPT_DIR, "scheduler_wrapper.py")}" '
            f'--run daily-brief'
        ),
        "work_dir": VAULT_ROOT,
        "description": "Daily brief + plan generation (daily 7:15 AM)",
    },
    "JARVIS_MiddayScan": {
        "schedule": "DAILY",
        "start_time": "13:00",
        "command": (
            f'"{PYTHON_EXE}" "{os.path.join(SCRIPT_DIR, "scheduler_wrapper.py")}" '
            f'--run ingest'
        ),
        "work_dir": VAULT_ROOT,
        "description": "Mid-day file scan for new inbox items (daily 1:00 PM)",
    },
}


def setup_logging():
    log_file = os.path.join(LOG_DIR, f"scheduler_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    return logging.getLogger("scheduler")


def run_schtasks(args: list, check: bool = True) -> subprocess.CompletedProcess:
    """运行 schtasks.exe 命令"""
    cmd = ["schtasks.exe"] + args
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if check and result.returncode != 0:
        logging.getLogger("scheduler").error(f"schtasks failed: {result.stderr}")
    return result


def install_tasks():
    """注册所有计划任务"""
    log = setup_logging()
    log.info("=== Installing JARVIS scheduled tasks ===")

    for task_name, cfg in TASKS.items():
        schtasks_args = [
            "/Create",
            "/TN", task_name,
            "/TR", cfg["command"],
            "/SC", cfg["schedule"],
            "/ST", cfg["start_time"],
            "/F",  # force overwrite
            "/RL", "HIGHEST",  # highest privileges
        ]
        result = run_schtasks(schtasks_args, check=False)
        if result.returncode == 0:
            log.info(f"  [OK] {task_name}: {cfg['start_time']} {cfg['schedule']}")
        else:
            log.error(f"  [FAIL] {task_name}: {result.stderr.strip()}")
            # Try without /RL HIGHEST if it fails
            schtasks_args_no_rl = [a for a in schtasks_args if a not in ("/RL", "HIGHEST")]
            if "/RL" in schtasks_args:
                result2 = run_schtasks(schtsasks_args_no_rl, check=False)
                if result2.returncode == 0:
                    log.info(f"  [OK] {task_name} (without /RL): {cfg['start_time']}")
                else:
                    log.error(f"  [FAIL] {task_name} (retry): {result2.stderr.strip()}")

    log.info("=== Installation complete ===")


def uninstall_tasks():
    """删除所有计划任务"""
    log = setup_logging()
    log.info("=== Uninstalling JARVIS scheduled tasks ===")

    for task_name in TASKS:
        result = run_schtasks(
            ["/Delete", "/TN", task_name, "/F"],
            check=False,
        )
        if result.returncode == 0:
            log.info(f"  [OK] Deleted: {task_name}")
        elif "does not exist" in result.stderr.lower() or "不存在" in result.stderr:
            log.info(f"  [SKIP] Not found: {task_name}")
        else:
            log.error(f"  [FAIL] {task_name}: {result.stderr.strip()}")

    log.info("=== Uninstall complete ===")


def list_tasks():
    """列出所有 JARVIS 任务"""
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/FO", "LIST", "/V"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if result.returncode != 0:
        print("No JARVIS tasks found or schtasks error.")
        print(result.stderr)
        return
    # 精简输出
    lines = result.stdout.split("\n")
    current = {}
    for line in lines:
        line = line.strip()
        if not line:
            if current:
                print(f"Task: {current.get('TaskName', '?')}")
                print(f"  Status: {current.get('Status', '?')}")
                print(f"  Schedule: {current.get('Schedule Type', '?')} @ {current.get('Start Time', '?')}")
                print(f"  Last Run: {current.get('Last Run Time', 'Never')}")
                print(f"  Next Run: {current.get('Next Run Time', 'N/A')}")
                print()
                current = {}
        elif ":" in line:
            key, val = line.split(":", 1)
            current[key.strip()] = val.strip()
    if current:
        print(f"Task: {current.get('TaskName', '?')}")
        print(f"  Status: {current.get('Status', '?')}")
        print(f"  Schedule: {current.get('Schedule Type', '?')} @ {current.get('Start Time', '?')}")
        print()


def run_daily_brief_pipeline():
    """执行日报+计划生成管线"""
    log = setup_logging()
    log.info("=== Daily Brief Pipeline START ===")

    ingestion_script = os.path.join(SCRIPT_DIR, "ingestion_agent.py")
    brief_script = os.path.join(SCRIPT_DIR, "daily_brief_gen.py")
    plan_script = os.path.join(SCRIPT_DIR, "plan_generator.py")
    email_script = os.path.join(SCRIPT_DIR, "email_ingestion.py")

    # Step 1: 文件摄入扫描
    log.info("Step 1/4: File ingestion scan...")
    r1 = subprocess.run([PYTHON_EXE, ingestion_script, "--scan"], cwd=VAULT_ROOT,
                        capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    if r1.returncode == 0:
        log.info("  File ingestion complete.")
    else:
        log.warning(f"  File ingestion warning: {r1.stderr[:200]}")

    # Step 1b: 邮件摄入
    log.info("Step 2/4: Email ingestion...")
    r1b = subprocess.run([PYTHON_EXE, email_script, "--days", "1", "--summary"],
                         cwd=VAULT_ROOT,
                         capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    if r1b.returncode == 0:
        log.info("  Email ingestion complete.")
    else:
        log.warning(f"  Email warning: {r1b.stderr[:200]}")

    # Step 2: 日报生成
    log.info("Step 3/4: Daily brief generation...")
    r2 = subprocess.run([PYTHON_EXE, brief_script], cwd=VAULT_ROOT,
                        capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    if r2.returncode == 0:
        brief_output = r2.stdout.strip() if r2.stdout else ""
        log.info(f"  Brief generated: {brief_output[-100:]}")
    else:
        log.error(f"  Brief failed: {r2.stderr[:200]}")

    # Step 3: 计划生成
    log.info("Step 4/4: Plan generation...")
    r3 = subprocess.run([PYTHON_EXE, plan_script], cwd=VAULT_ROOT,
                        capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    if r3.returncode == 0:
        log.info("  Plans generated.")
    else:
        log.error(f"  Plan failed: {r3.stderr[:200]}")

    log.info("=== Daily Brief Pipeline END ===")


def run_ingestion_scan():
    """仅执行摄入扫描 + 邮件检查"""
    log = setup_logging()
    log.info("=== Midday Scan ===")
    ingestion_script = os.path.join(SCRIPT_DIR, "ingestion_agent.py")
    email_script = os.path.join(SCRIPT_DIR, "email_ingestion.py")

    r = subprocess.run([PYTHON_EXE, ingestion_script], cwd=VAULT_ROOT,
                       capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode == 0:
        log.info("  File scan complete.")
    else:
        log.warning(f"  File scan warning: {r.stderr[:200]}")

    r2 = subprocess.run([PYTHON_EXE, email_script, "--days", "1", "--summary"],
                        cwd=VAULT_ROOT,
                        capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    if r2.returncode == 0:
        log.info("  Email check complete.")
    else:
        log.warning(f"  Email warning: {r2.stderr[:200]}")

    log.info("=== Midday Scan END ===")


def cmd_status():
    """显示所有任务状态"""
    log = setup_logging()
    log.info("Checking JARVIS task status...")
    list_tasks()

    # 检查最近日志
    log_files = sorted(
        [f for f in os.listdir(LOG_DIR) if f.startswith("scheduler_")],
        reverse=True,
    )
    if log_files:
        print(f"\nRecent logs: {LOG_DIR}")
        for lf in log_files[:3]:
            log_path = os.path.join(LOG_DIR, lf)
            print(f"  {lf}: {os.path.getsize(log_path)} bytes")
            with open(log_path, "r", encoding="utf-8") as f:
                last_lines = f.readlines()[-3:]
                for line in last_lines:
                    print(f"    {line.strip()}")


def main():
    import io
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="JARVIS Windows 计划任务管理")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", action="store_true", help="注册所有计划任务")
    group.add_argument("--uninstall", action="store_true", help="删除所有计划任务")
    group.add_argument("--list", action="store_true", help="列出当前任务")
    group.add_argument("--status", action="store_true", help="查看任务状态和最近日志")
    group.add_argument("--run", choices=["daily-brief", "ingest"],
                       help="手动触发任务")
    args = parser.parse_args()

    if args.install:
        install_tasks()
    elif args.uninstall:
        uninstall_tasks()
    elif args.list:
        list_tasks()
    elif args.status:
        cmd_status()
    elif args.run == "daily-brief":
        run_daily_brief_pipeline()
    elif args.run == "ingest":
        run_ingestion_scan()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

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
        "description": "Daily brief + plan + health + archive (daily 7:15 AM)",
    },
    "JARVIS_MiddayScan": {
        "schedule": "DAILY",
        "start_time": "13:00",
        "command": (
            f'"{PYTHON_EXE}" "{os.path.join(SCRIPT_DIR, "scheduler_wrapper.py")}" '
            f'--run ingest'
        ),
        "work_dir": VAULT_ROOT,
        "description": "Mid-day file scan + email check (daily 1:00 PM)",
    },
    "JARVIS_WeeklyReport": {
        "schedule": "WEEKLY",
        "start_time": "16:00",
        "command": (
            f'"{PYTHON_EXE}" "{os.path.join(SCRIPT_DIR, "scheduler_wrapper.py")}" '
            f'--run weekly-report'
        ),
        "work_dir": VAULT_ROOT,
        "description": "Weekly report generation (Fri 4:00 PM)",
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
    """执行日报+计划生成管线（含健康检查 + 归档）"""
    log = setup_logging()
    log.info("=== Daily Brief Pipeline START ===")

    ingestion_script = os.path.join(SCRIPT_DIR, "ingestion_agent.py")
    brief_script = os.path.join(SCRIPT_DIR, "daily_brief_gen.py")
    plan_script = os.path.join(SCRIPT_DIR, "plan_generator.py")
    email_script = os.path.join(SCRIPT_DIR, "email_ingestion.py")

    # 编码环境变量 + API keys（Windows Task Scheduler 不继承 Claude 的 env）
    utf8_env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    # 从 Claude settings 继承 API keys（如果存在）
    for key in ["SILICONFLOW_API_KEY", "JARVIS_API_KEY",
                "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY",
                "ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_SONNET_MODEL"]:
        if key in os.environ:
            utf8_env[key] = os.environ[key]

    # Step 1: 文件摄入扫描（限流+跳过邮件附件，容忍超时）
    log.info("Step 1/5: File ingestion scan (max 20/dir, skip inbox)...")
    try:
        r1 = subprocess.run(
            [PYTHON_EXE, ingestion_script, "--scan",
             "--max-files", "20", "--skip-inbox-attachments"],
            cwd=VAULT_ROOT, env=utf8_env,
            capture_output=True, encoding="utf-8", errors="replace", timeout=90)
        if r1.returncode == 0:
            log.info("  File ingestion complete.")
        else:
            log.warning(f"  File ingestion warning: {r1.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.warning("  File ingestion timed out (90s), continuing pipeline.")
    except Exception as e:
        log.warning(f"  File ingestion error: {e}")

    # Step 2: 邮件摄入
    log.info("Step 2/5: Email ingestion...")
    try:
        r2 = subprocess.run([PYTHON_EXE, email_script, "--days", "1", "--summary"],
                             cwd=VAULT_ROOT, env=utf8_env,
                             capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        if r2.returncode == 0:
            log.info("  Email ingestion complete.")
        else:
            log.warning(f"  Email warning: {r2.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.warning("  Email ingestion timed out (60s), continuing pipeline.")
    except Exception as e:
        log.warning(f"  Email ingestion error: {e}")

    # Step 3: 日报生成（含AI摘要 + 归档）
    log.info("Step 3/5: Daily brief generation...")
    try:
        r3 = subprocess.run([PYTHON_EXE, brief_script], cwd=VAULT_ROOT, env=utf8_env,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        if r3.returncode == 0:
            brief_output = r3.stdout.strip() if r3.stdout else ""
            log.info(f"  Brief generated: {brief_output[-100:]}")
        else:
            log.error(f"  Brief failed: {r3.stderr[:200]}")
    except Exception as e:
        log.error(f"  Brief exception: {e}")

    # Step 4: 计划生成
    log.info("Step 4/5: Plan generation...")
    try:
        r4 = subprocess.run([PYTHON_EXE, plan_script], cwd=VAULT_ROOT, env=utf8_env,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        if r4.returncode == 0:
            log.info("  Plans generated.")
        else:
            log.error(f"  Plan failed: {r4.stderr[:200]}")
    except Exception as e:
        log.error(f"  Plan exception: {e}")

    # Step 5: 健康检查（快速模式）
    log.info("Step 5/5: Health check (quick)...")
    try:
        health_script = os.path.join(SCRIPT_DIR, "health_check.py")
        r5 = subprocess.run([PYTHON_EXE, health_script, "--quick", "--json"],
                           cwd=VAULT_ROOT, env=utf8_env,
                           capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        if r5.returncode == 0:
            result = json.loads(r5.stdout)
            healthy = result.get("summary", {}).get("healthy", False)
            if not healthy:
                log.warning(f"  Health issues: {result['summary'].get('errors_detail', {})}")
            else:
                log.info("  Health check OK.")
        else:
            log.warning(f"  Health check failed: {r5.stderr[:100]}")
    except Exception as e:
        log.warning(f"  Health check error: {e}")

    log.info("=== Daily Brief Pipeline END ===")


def run_ingestion_scan():
    """仅执行摄入扫描 + 邮件检查"""
    log = setup_logging()
    log.info("=== Midday Scan ===")
    ingestion_script = os.path.join(SCRIPT_DIR, "ingestion_agent.py")
    email_script = os.path.join(SCRIPT_DIR, "email_ingestion.py")

    utf8_env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1"}

    # 默认快速扫描（跳过邮件附件，限制文件数）
    try:
        r = subprocess.run([PYTHON_EXE, ingestion_script], cwd=VAULT_ROOT,
                           env=utf8_env,
                           capture_output=True, encoding="utf-8", errors="replace", timeout=90)
        if r.returncode == 0:
            log.info("  File scan complete.")
        else:
            log.warning(f"  File scan warning: {r.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.warning("  File scan timed out (90s), continuing.")
    except Exception as e:
        log.warning(f"  File scan error: {e}")

    try:
        r2 = subprocess.run([PYTHON_EXE, email_script, "--days", "1", "--summary"],
                            cwd=VAULT_ROOT, env=utf8_env,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        if r2.returncode == 0:
            log.info("  Email check complete.")
        else:
            log.warning(f"  Email warning: {r2.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.warning("  Email check timed out (60s), continuing.")
    except Exception as e:
        log.warning(f"  Email check error: {e}")

    log.info("=== Midday Scan END ===")


def run_weekly_report():
    """执行周报生成"""
    log = setup_logging()
    log.info("=== Weekly Report START ===")
    weekly_script = os.path.join(SCRIPT_DIR, "weekly_report_gen.py")

    utf8_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for key in ["SILICONFLOW_API_KEY", "JARVIS_API_KEY",
                "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY",
                "ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_SONNET_MODEL"]:
        if key in os.environ:
            utf8_env[key] = os.environ[key]

    try:
        r = subprocess.run([PYTHON_EXE, weekly_script], cwd=VAULT_ROOT, env=utf8_env,
                          capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        if r.returncode == 0:
            log.info(f"  Weekly report generated: {r.stdout.strip()[-100:]}")
        else:
            log.error(f"  Weekly report failed: {r.stderr[:200]}")
    except Exception as e:
        log.error(f"  Weekly report exception: {e}")

    log.info("=== Weekly Report END ===")


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
    group.add_argument("--run", choices=["daily-brief", "ingest", "weekly-report"],
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
    elif args.run == "weekly-report":
        run_weekly_report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

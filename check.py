# check.py 每日检查 + 自动补跑：确认今天的阅读任务（wxread 工作流）是否成功执行
#
# 三道拦截设计（时间均为北京时间，全部避开整点以躲开 GitHub Actions 调度高峰）：
#   道一: deploy.yml 主任务（每天 00:23）
#   道二: 本脚本上午窗口（每天 08:41），未成功则自动触发补跑并等待验证
#   道三: 本脚本晚间窗口（每天 17:37），最终兜底，补跑后仍失败才推送告警
#
# 补跑通过 GITHUB_TOKEN 调用 workflow_dispatch 触发 deploy.yml，
# 完整复用其 secrets/环境配置；deploy.yml 内有 guard.py 防止重复刷时长。
import os
import time
import logging
from datetime import datetime, timedelta, timezone

import requests

from push import push
from config import PUSH_METHOD

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BJT = timezone(timedelta(hours=8))
# 注意：API 路径只认 workflow 文件名（或数字 ID），不认 workflow 显示名
# 阅读任务对应的文件是 deploy.yml（显示名为 wxread）
WORKFLOW_FILE = "deploy.yml"
API_BASE = "https://api.github.com"
# 补跑一次约 6 分钟；轮询最长等 15 分钟
WAIT_TIMEOUT_SECONDS = 15 * 60
POLL_INTERVAL_SECONDS = 30


def api_headers(token):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def today_midnight_utc():
    """今天（北京时间）0 点对应的 UTC 时间"""
    now_bjt = datetime.now(BJT)
    midnight_bjt = now_bjt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_bjt.astimezone(timezone.utc)


def list_runs_today(repo, token):
    """查询 deploy.yml 今天（北京时间）的运行记录"""
    since = today_midnight_utc()
    url = f"{API_BASE}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs"
    params = {"per_page": 30, "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"}

    response = requests.get(url, headers=api_headers(token), params=params, timeout=15)
    response.raise_for_status()
    return response.json().get("workflow_runs", [])


def has_success_run(runs):
    return any(
        run.get("status") == "completed" and run.get("conclusion") == "success"
        for run in runs
    )


def find_today_success_run(repo, token):
    """查询今天是否有成功的阅读工作流运行记录"""
    runs = list_runs_today(repo, token)

    if not runs:
        logging.info("今天（北京时间）没有找到 %s 的运行记录。", WORKFLOW_FILE)
        return None

    for run in runs:
        logging.info(
            "运行记录: created_at=%s status=%s conclusion=%s",
            run.get("created_at"), run.get("status"), run.get("conclusion"),
        )
        if run.get("conclusion") == "success":
            return run
    return None


def dispatch_makeup_run(repo, token):
    """通过 workflow_dispatch 触发一次补跑（GITHUB_TOKEN 需要 actions: write 权限）"""
    url = f"{API_BASE}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    ref = os.getenv("GITHUB_REF_NAME") or "main"
    response = requests.post(
        url, headers=api_headers(token), json={"ref": ref}, timeout=15
    )
    if response.status_code == 204:
        logging.info("已触发补跑（workflow_dispatch, ref=%s）。", ref)
        return True
    logging.error(
        "触发补跑失败: HTTP %s %s", response.status_code, response.text[:200]
    )
    return False


def wait_for_makeup_result(repo, token):
    """轮询等待补跑结束；返回 True 表示今天已有成功的运行"""
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    # 先等一会儿，让 dispatch 出来的运行记录出现在 API 里
    time.sleep(POLL_INTERVAL_SECONDS)

    while time.time() < deadline:
        runs = list_runs_today(repo, token)
        if has_success_run(runs):
            logging.info("补跑已成功。")
            return True
        # 所有运行都已结束但仍无成功记录，且没有排队/进行中的运行 → 补跑失败
        if runs and all(
            run.get("status") not in ("queued", "in_progress") for run in runs
        ):
            logging.warning("补跑已结束但未成功。")
            return False
        time.sleep(POLL_INTERVAL_SECONDS)

    logging.warning("等待补跑结果超时。")
    return False


def push_failure(repo, reason):
    actions_url = f"https://github.com/{repo}/actions/workflows/{WORKFLOW_FILE}"
    content = (
        "微信读书自动阅读：今天的阅读任务未成功执行！\n"
        f"原因：{reason}\n"
        f"请前往 Actions 页面检查：{actions_url}"
    )
    logging.warning("开始推送失败通知...")
    push(content, PUSH_METHOD, is_success=False, title="微信阅读-今日任务未执行")


def main():
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")

    if not repo or not token:
        logging.error("缺少 GITHUB_REPOSITORY / GITHUB_TOKEN，check.py 只支持在 GitHub Actions 中运行。")
        raise SystemExit(1)

    success_run = find_today_success_run(repo, token)

    if success_run:
        logging.info("今天的阅读任务已成功执行（run #%s），无需处理。",
                     success_run.get("run_number"))
        return

    # 道二/道三：未成功 → 自动补跑一次
    logging.warning("今天的阅读任务未成功执行，尝试自动补跑...")
    if not dispatch_makeup_run(repo, token):
        push_failure(repo, "自动补跑触发失败（请确认 check.yml 有 actions: write 权限）")
        raise SystemExit(1)

    if wait_for_makeup_result(repo, token):
        logging.info("补跑成功，今天的阅读任务已完成，无需告警。")
        return

    push_failure(repo, "自动补跑后仍未成功（可能 cookie 已过期或阅读接口异常）")
    raise SystemExit(1)


if __name__ == "__main__":
    main()

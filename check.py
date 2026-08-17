# check.py 每日检查：确认今天的阅读任务（wxread 工作流）是否成功执行
# 成功则静默退出；未成功才推送失败通知
import os
import logging
from datetime import datetime, timedelta, timezone

import requests

from push import push
from config import PUSH_METHOD

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BJT = timezone(timedelta(hours=8))
WORKFLOW_FILE = "wxread.yml"


def today_midnight_utc():
    """今天（北京时间）0 点对应的 UTC 时间"""
    now_bjt = datetime.now(BJT)
    midnight_bjt = now_bjt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_bjt.astimezone(timezone.utc)


def find_today_success_run(repo, token):
    """查询今天是否有成功的阅读工作流运行记录"""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    since = today_midnight_utc()
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs"
    params = {"per_page": 30, "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"}

    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    runs = response.json().get("workflow_runs", [])

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


def main():
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")

    if not repo or not token:
        logging.error("缺少 GITHUB_REPOSITORY / GITHUB_TOKEN，check.py 只支持在 GitHub Actions 中运行。")
        raise SystemExit(1)

    success_run = find_today_success_run(repo, token)

    if success_run:
        logging.info("今天的阅读任务已成功执行（run #%s），无需提醒。", success_run.get("run_number"))
        return

    actions_url = f"https://github.com/{repo}/actions/workflows/{WORKFLOW_FILE}"
    content = (
        "微信读书自动阅读：今天的阅读任务未成功执行！\n"
        "可能原因：GitHub Actions 调度失败、cookie 过期或网络问题。\n"
        f"请前往 Actions 页面检查：{actions_url}"
    )
    logging.warning("今天的阅读任务未成功执行，开始推送失败通知...")
    push(content, PUSH_METHOD, is_success=False, title="微信阅读-今日任务未执行")


if __name__ == "__main__":
    main()

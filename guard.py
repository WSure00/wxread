# guard.py 运行前守卫：检查今天（北京时间）是否已有成功的阅读记录
# 已有成功记录则输出 skip=true，deploy.yml 据此跳过 main.py，
# 避免延迟的定时任务与自动补跑重复刷时长。
import os
from datetime import datetime, timedelta, timezone

import requests

BJT = timezone(timedelta(hours=8))
WORKFLOW_FILE = "deploy.yml"


def main():
    if os.getenv("FORCE") == "true":
        # 手动触发带 force=true 时强制执行（如更新 key 后验证），跳过去重检查
        write_output("skip=false")
        print("force=true，跳过 guard 去重检查")
        return

    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    if not repo or not token:
        # 拿不到环境变量时不拦截，交给主脚本正常执行
        write_output("skip=false")
        return

    midnight_bjt = datetime.now(BJT).replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight_bjt.astimezone(timezone.utc)

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"per_page": 30, "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"}

    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    runs = response.json().get("workflow_runs", [])

    # 只认已结束且成功的运行（当前运行自身是 in_progress，不会被误判）
    done = any(
        run.get("status") == "completed" and run.get("conclusion") == "success"
        for run in runs
    )
    write_output("skip=true" if done else "skip=false")
    print(f"今日运行记录数: {len(runs)}, 已有成功记录: {done}")


def write_output(value):
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{value}\n")
    print(f"guard 输出: {value}")


if __name__ == "__main__":
    main()

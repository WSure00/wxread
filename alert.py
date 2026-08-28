# alert.py 失败告警：阅读任务执行失败（进程非零退出）时由 workflow 的
# failure() 步骤调用，推送失败通知。
import logging

from push import push
from config import PUSH_METHOD

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    content = (
        "微信读书自动阅读：本次阅读任务执行失败！\n"
        "可能原因：cookie 已彻底过期（WXREAD_CURL_BASH 需更新）、"
        "阅读接口异常或网络问题。\n"
        "下一个时间槽会自动重试；若多次失败请前往 Actions 页面查看日志。"
    )
    logging.warning("阅读任务失败，推送告警...")
    push(content, PUSH_METHOD, is_success=False, title="微信阅读-任务执行失败")


if __name__ == "__main__":
    main()

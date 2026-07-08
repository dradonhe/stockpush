"""
F5.1 统一推送管理器
支持飞书、Telegram 多通道推送，根据 push_method 配置分发
"""
import logging
from typing import Dict, Any, Optional

from .feishu_pusher import FeishuPusher
from .telegram_pusher import TelegramPusher

logger = logging.getLogger(__name__)

# 需要代理的推送方法名
_PROXY_METHODS = {
    'push', 'push_card', 'push_signal', 'push_signal_batch',
    'push_dividend_notice', 'push_datasource_switch', 'push_error',
    'push_startup', 'push_shutdown', 'push_data_complete', 'test',
}

VALID_METHODS = ("feishu", "telegram", "both")


class PushManager:
    """统一推送管理器

    根据 push_method 配置将推送分发到对应通道:
    - "feishu": 仅飞书
    - "telegram": 仅 Telegram
    - "both": 同时推送两个通道
    """

    def __init__(self, feishu: Optional[FeishuPusher] = None,
                 telegram: Optional[TelegramPusher] = None,
                 method: str = "feishu"):
        self.feishu = feishu or FeishuPusher()
        self.telegram = telegram or TelegramPusher()
        self.method = method if method in VALID_METHODS else "feishu"

    def __getattr__(self, name: str):
        """代理推送方法到选中的通道"""
        if name not in _PROXY_METHODS:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        def dispatch(*args, **kwargs):
            results: Dict[str, Any] = {}

            if self.method in ("feishu", "both"):
                fn = getattr(self.feishu, name, None)
                if fn:
                    try:
                        results["feishu"] = fn(*args, **kwargs)
                    except Exception as e:
                        logger.error("Feishu %s failed: %s", name, e)
                        results["feishu"] = {"success": False, "message": str(e)}

            if self.method in ("telegram", "both"):
                fn = getattr(self.telegram, name, None)
                if fn:
                    try:
                        results["telegram"] = fn(*args, **kwargs)
                    except Exception as e:
                        logger.error("Telegram %s failed: %s", name, e)
                        results["telegram"] = {"success": False, "message": str(e)}

            # 返回第一个成功的结果，否则返回第一个结果
            for key in ["feishu", "telegram"]:
                r = results.get(key)
                if r and r.get("success"):
                    return r
            return (results.get("feishu")
                    or results.get("telegram")
                    or {"success": False, "message": "无可用推送通道"})

        return dispatch

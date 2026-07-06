"""
F5.1 飞书推送模块
支持 Webhook 推送、HMAC 签名校验、测试消息、配置管理
"""
import hashlib
import hmac
import base64
import time as time_module
import requests
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class FeishuPusher:
    """飞书推送器"""

    def __init__(self, webhook_url: Optional[str] = None, enabled: bool = False,
                 sign_secret: Optional[str] = None, sign_enabled: bool = False):
        self.webhook_url = webhook_url
        self.enabled = enabled
        self.sign_secret = sign_secret
        self.sign_enabled = sign_enabled

    def set_config(self, webhook_url: str, enabled: bool = True,
                   sign_secret: Optional[str] = None, sign_enabled: bool = False):
        self.webhook_url = webhook_url
        self.enabled = enabled
        self.sign_secret = sign_secret
        self.sign_enabled = sign_enabled

    def _build_payload(self, message: str, msg_type: str = "text") -> dict:
        payload = {"msg_type": msg_type, "content": {"text": message}}
        if self.sign_enabled and self.sign_secret:
            ts = int(time_module.time())
            string_to_sign = f"{ts}\n{self.sign_secret}"
            sign = base64.b64encode(
                hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            ).decode()
            payload["timestamp"] = str(ts)
            payload["sign"] = sign
        return payload

    def push(self, message: str, msg_type: str = "text") -> Dict[str, Any]:
        if not self.enabled or not self.webhook_url:
            logger.warning("Push skipped: enabled=%s, webhook=%s", self.enabled, bool(self.webhook_url))
            return {"success": False, "message": "飞书未启用或未配置 Webhook"}
        payload = self._build_payload(message, msg_type)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(self.webhook_url, json=payload,
                                         headers={"Content-Type": "application/json"}, timeout=10)
                result = response.json()
                if result.get("code") == 0 and response.status_code == 200:
                    logger.info("Push success: %s", message.split('\n')[0][:60])
                    return {"success": True, "message": "推送成功"}
                code = result.get("code")
                msg = result.get("msg", "Unknown error")
                if code == 11232 and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("Push rate limited (code=%s), retrying in %ds (attempt %d/%d)...",
                                   code, wait, attempt + 1, max_retries)
                    time_module.sleep(wait)
                    continue
                logger.warning("Push failed: code=%s msg=%s", code, msg)
                return {"success": False, "message": f"推送失败: {msg}"}
            except requests.exceptions.Timeout:
                logger.warning("Push timeout: webhook=%s", self.webhook_url[:40])
                return {"success": False, "message": "推送超时"}
            except requests.exceptions.RequestException as e:
                logger.error("Push error: %s", e)
                return {"success": False, "message": f"推送异常: {str(e)}"}
        return {"success": False, "message": "推送失败: 超出最大重试次数"}

    def push_signal(self, symbol: str, name: str, signal_type: str,
                    time_str: str, period: str, indicator: str,
                    source: str = "xtick",
                    buy_status: str = "", sell_status: str = "",
                    open_price: float = 0.0) -> Dict[str, Any]:
        open_line = f"开盘价: {open_price:.3f}\n" if open_price else ""
        status_line = ""
        if signal_type == "buy" and buy_status:
            status_line = f"买点类别: {buy_status}\n"
        elif signal_type == "sell" and sell_status:
            status_line = f"卖点类别: {sell_status}\n"
        message = f"""[F5.1 实时监控]
标的: {symbol} {name}
信号: {signal_type}
时间: {time_str}
周期: {period}{open_line}{status_line}触发条件: {indicator}
数据源: {source}"""
        return self.push(message)

    def push_dividend_notice(self, symbol: str, name: str) -> Dict[str, Any]:
        message = f"""[F5.1 监控通知]
标的: {symbol} {name}
事件: 今日为除权除息日，已全量更新数据
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
来源: F5.1 自动检测"""
        return self.push(message)

    def push_datasource_switch(self, from_source: str, to_source: str) -> Dict[str, Any]:
        message = f"""[F5.1 系统通知]
数据源自动切换
从: {from_source}
切换至: {to_source}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        return self.push(message)

    def push_error(self, error_message: str, context: str = "") -> Dict[str, Any]:
        message = f"""[F5.1 错误通知]
错误: {error_message}
上下文: {context}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        return self.push(message)

    def push_startup(self, watchlist_count: int, datasource: str) -> Dict[str, Any]:
        """推送启动通知"""
        message = (
            "[F5.1 实时监控]\n"
            f"状态: 已启动\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"自选股: {watchlist_count} 只\n"
            f"数据源: {datasource}"
        )
        return self.push(message)

    def push_shutdown(self, runtime: str) -> Dict[str, Any]:
        """推送停止通知"""
        message = (
            "[F5.1 实时监控]\n"
            f"状态: 已停止\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"运行时长: {runtime}"
        )
        return self.push(message)

    def push_data_complete(self, results: List[Tuple]) -> Dict[str, Any]:
        """推送数据补全结果通知"""
        lines = ["[F5.1 实时监控]", "数据完整性检查完成"]
        for symbol, period, ok, cnt, src in results:
            icon = "\xe2\x9c\x85" if ok else "\xe2\x9a\xa0"
            detail = f"({cnt}条, {src})" if ok else "缺失, 已补全"
            lines.append(f"{symbol} {period}: {icon} {detail}")
        return self.push("\n".join(lines))

    def test(self) -> Dict[str, Any]:
        message = f"""[F5.1 测试消息]
这是一条测试消息
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
配置状态: {'已启用' if self.enabled else '未启用'}
签名校验: {'已启用' if self.sign_enabled else '未启用'}"""
        return self.push(message)


_pusher_instance: Optional[FeishuPusher] = None


def get_pusher() -> FeishuPusher:
    global _pusher_instance
    if _pusher_instance is None:
        _pusher_instance = FeishuPusher()
    return _pusher_instance


def init_pusher(webhook_url: str, enabled: bool = True,
                sign_secret: Optional[str] = None, sign_enabled: bool = False) -> FeishuPusher:
    global _pusher_instance
    _pusher_instance = FeishuPusher(webhook_url=webhook_url, enabled=enabled,
                                     sign_secret=sign_secret, sign_enabled=sign_enabled)
    return _pusher_instance

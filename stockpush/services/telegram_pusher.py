"""
F5.1 Telegram 推送模块
支持 Bot API 推送、重试、分段发送
"""
import time as time_module
import requests
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096



def _format_channel_states(channel_states: str) -> str:
    """对通道状态字符串的30m_mm2（第4位）标记颜色。

    红多: 第4位为"多", 或(第4位为"震"且第5位为"多")
    其他: 绿色
    """
    parts = channel_states.split("/")
    if len(parts) < 5:
        return channel_states
    val4 = parts[3]   # 30m_mm2
    val5 = parts[4]   # 30m_mm3
    if val4 == "多" or (val4 == "震" and val5 == "多"):
        color = "🔴"
    else:
        color = "🟢"
    parts[3] = f"{color}{val4}"
    return "/".join(parts)
class TelegramPusher:
    """Telegram 推送器"""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None,
                 enabled: bool = False):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled

    def set_config(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _send_message(self, text: str, parse_mode: str = "HTML") -> Dict[str, Any]:
        """发送单条消息到 Telegram"""
        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, timeout=15)
                result = response.json()
                if result.get("ok") and response.status_code == 200:
                    logger.info("Telegram push success")
                    return {"success": True, "message": "推送成功"}
                code = result.get("error_code", 0)
                desc = result.get("description", "Unknown error")
                if code == 429 and attempt < max_retries - 1:
                    retry_after = result.get("parameters", {}).get("retry_after", 2 ** attempt)
                    wait = max(retry_after, 2 ** attempt)
                    logger.warning("Telegram rate limited (429), retrying in %ds (attempt %d/%d)...",
                                   wait, attempt + 1, max_retries)
                    time_module.sleep(wait)
                    continue
                logger.warning("Telegram push failed: code=%s desc=%s", code, desc)
                return {"success": False, "message": f"推送失败: {desc}"}
            except requests.exceptions.Timeout:
                logger.warning("Telegram push timeout")
                return {"success": False, "message": "推送超时"}
            except requests.exceptions.RequestException as e:
                logger.error("Telegram push error: %s", e)
                return {"success": False, "message": f"推送异常: {str(e)}"}
        return {"success": False, "message": "推送失败: 超出最大重试次数"}

    def push(self, message: str, parse_mode: str = "HTML") -> Dict[str, Any]:
        """推送消息，自动处理超长分段"""
        if not self.enabled or not self.configured:
            logger.warning("Telegram push skipped: enabled=%s, configured=%s",
                           self.enabled, self.configured)
            return {"success": False, "message": "Telegram 未启用或未配置"}

        # Escape HTML special chars if using HTML parse mode (but preserve our tags)
        # For safety, convert bare &, <, > only outside of known tags
        if parse_mode == "HTML":
            text = self._escape_html(message)
        else:
            text = message

        # Telegram 消息长度限制 4096，超长时分段发送
        if len(text) <= MAX_MESSAGE_LENGTH:
            return self._send_message(text, parse_mode)

        # 分段发送
        chunks = self._split_message(text, MAX_MESSAGE_LENGTH)
        last_result = {"success": True, "message": "推送成功"}
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                prefix = f"({i + 1}/{len(chunks)})\n"
                chunk = prefix + chunk
            result = self._send_message(chunk, parse_mode)
            if not result.get("success"):
                logger.warning("Telegram chunk %d/%d failed", i + 1, len(chunks))
                last_result = result
        return last_result

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special chars but preserve <b>, <i>, <code>, <pre>, <a> tags"""
        import re
        # Protect known safe tags
        safe_tags = ['b', 'i', 'u', 's', 'code', 'pre', 'a']
        placeholder_map = {}
        for tag in safe_tags:
            pattern = re.compile(r'(<' + tag + r'[^>]*>|</' + tag + r'>)')
            for match in pattern.finditer(text):
                key = f"__TAG_{len(placeholder_map)}__"
                placeholder_map[key] = match.group(0)
                text = text.replace(match.group(0), key, 1)

        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        for key, value in placeholder_map.items():
            text = text.replace(key, value)
        return text

    @staticmethod
    def _split_message(text: str, max_len: int) -> List[str]:
        """按换行分割消息，尽量保持行的完整性"""
        lines = text.split('\n')
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 <= max_len:
                current = (current + '\n' + line) if current else line
            else:
                if current:
                    chunks.append(current)
                # 如果单行超长，强制截断
                while len(line) > max_len:
                    chunks.append(line[:max_len])
                    line = line[max_len:]
                current = line
        if current:
            chunks.append(current)
        return chunks

    def push_card(self, card: dict) -> Dict[str, Any]:
        """推送卡片消息（Telegram 不支持交互式卡片，转为 HTML 格式发送）"""
        if not self.enabled or not self.configured:
            logger.warning("Telegram push skipped: enabled=%s, configured=%s",
                           self.enabled, self.configured)
            return {"success": False, "message": "Telegram 未启用或未配置"}

        header = card.get("header", {}).get("title", {}).get("content", "")
        elements = card.get("elements", [])
        lines = [f"<b>{header}</b>"] if header else []
        for el in elements:
            tag = el.get("tag", "")
            if tag == "div":
                text = el.get("text", {}).get("content", "")
                if text:
                    lines.append(text)
            elif tag == "hr":
                lines.append("───")
        return self.push("\n".join(lines))

    def push_signal(self, symbol: str, name: str, signal_type: str,
                    time_str: str, period: str, indicator: str,
                    source: str = "xtick",
                    buy_status: str = "", sell_status: str = "",
                    open_price: float = 0.0) -> Dict[str, Any]:
        emoji = "🔔" if signal_type == "buy" else "🔕"
        open_line = f"开盘价: {open_price:.3f}\n" if open_price else ""
        status_line = ""
        if signal_type == "buy" and buy_status:
            status_line = f"买点类别: {buy_status}\n"
        elif signal_type == "sell" and sell_status:
            status_line = f"卖点类别: {sell_status}\n"
        message = (
            f"{emoji} <b>{symbol} {name}</b>\n"
            f"信号: {signal_type}\n"
            f"时间: {time_str}\n"
            f"周期: {period}\n"
            f"{open_line}"
            f"{status_line}"
            f"触发条件: {indicator}\n"
            f"数据源: {source}"
        )
        return self.push(message)

    def push_signal_batch(self, signals: list, func_name: str = "") -> Dict[str, Any]:
        """批量推送信号表格"""
        if not signals:
            return {"success": True, "message": "无信号"}

        lines = ["<b>📊 批量信号</b>", ""]
        if func_name:
            lines[0] = f"<b>📊 批量信号 [{func_name}]</b>"

        for s in signals:
            symbol = s.get("symbol", "")
            name = s.get("name", "")
            direction = s.get("direction", "")
            raw_time = s.get("time") or s.get("time_str", "")
            if hasattr(raw_time, "strftime"):
                time_str = raw_time.strftime("%H:%M")
            else:
                time_str = str(raw_time)
            period = s.get("period", "")
            indicator = s.get("indicator", "")
            open_price = s.get("open_price", 0.0)

            if " " in time_str:
                time_short = time_str.split(" ")[1][:5]
            elif len(time_str) == 5 and ":" in time_str:
                time_short = time_str
            else:
                time_short = time_str[:5]

            dir_emoji = "🟢" if direction == "buy" else "🔴"
            open_str = f"{open_price:.2f}" if open_price else ""
            channel_states = s.get("channel_states", "")

            line = f"{dir_emoji} <code>{symbol}</code> {name} | {period} | {time_short} | {indicator} | {open_str}"
            if channel_states:
                line += f"\n  通道: {_format_channel_states(channel_states)}"
            lines.append(line)

        return self.push("\n".join(lines))

    def push_dividend_notice(self, symbol: str, name: str) -> Dict[str, Any]:
        message = (
            "<b>[F5.1 监控通知]</b>\n"
            f"标的: {symbol} {name}\n"
            "事件: 今日为除权除息日，已全量更新数据\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "来源: F5.1 自动检测"
        )
        return self.push(message)

    def push_datasource_switch(self, from_source: str, to_source: str) -> Dict[str, Any]:
        message = (
            "<b>[F5.1 系统通知]</b>\n"
            "数据源自动切换\n"
            f"从: {from_source}\n"
            f"切换至: {to_source}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.push(message)

    def push_error(self, error_message: str, context: str = "") -> Dict[str, Any]:
        message = (
            "<b>[F5.1 错误通知]</b>\n"
            f"错误: {error_message}\n"
            f"上下文: {context}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.push(message)

    def push_startup(self, watchlist_count: int, datasource: str) -> Dict[str, Any]:
        """推送启动通知"""
        message = (
            "<b>[F5.1 实时监控]</b>\n"
            "状态: 已启动\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"自选股: {watchlist_count} 只\n"
            f"数据源: {datasource}"
        )
        return self.push(message)

    def push_shutdown(self, runtime: str) -> Dict[str, Any]:
        """推送停止通知"""
        message = (
            "<b>[F5.1 实时监控]</b>\n"
            "状态: 已停止\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"运行时长: {runtime}"
        )
        return self.push(message)

    def push_data_complete(self, results: List[Tuple]) -> Dict[str, Any]:
        """推送数据补全结果通知"""
        lines = ["<b>[F5.1 实时监控]</b>", "数据完整性检查完成"]
        for symbol, period, ok, cnt, src in results:
            icon = "✅" if ok else "⚠️"
            detail = f"({cnt}条, {src})" if ok else "缺失, 已补全"
            lines.append(f"{symbol} {period}: {icon} {detail}")
        return self.push("\n".join(lines))

    def test(self) -> Dict[str, Any]:
        message = (
            "<b>[F5.1 测试消息]</b>\n"
            "这是一条测试消息\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"配置状态: {'已启用' if self.enabled else '未启用'}\n"
            f"Bot Token: {'已配置' if self.bot_token else '未配置'}\n"
            f"Chat ID: {'已配置' if self.chat_id else '未配置'}"
        )
        return self.push(message)


_pusher_instance: Optional[TelegramPusher] = None


def get_pusher() -> TelegramPusher:
    global _pusher_instance
    if _pusher_instance is None:
        _pusher_instance = TelegramPusher()
    return _pusher_instance


def init_pusher(bot_token: str, chat_id: str, enabled: bool = True) -> TelegramPusher:
    global _pusher_instance
    _pusher_instance = TelegramPusher(bot_token, chat_id, enabled)
    return _pusher_instance

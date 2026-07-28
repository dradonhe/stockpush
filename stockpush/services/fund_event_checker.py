"""
F5.1 基金拆分/分红事件检查模块

通过天天基金 f10 页面获取基金的拆分（份额分拆）和分红（除权除息）事件。
替代 XTick 不支持的分红拆分查询。

数据来源: http://fundf10.eastmoney.com/fhsp_{code}.html
"""
import logging
import re
import time
from datetime import date
from typing import Dict, List, Optional, Any

import requests

logger = logging.getLogger(__name__)

# 缓存：避免同一交易日重复请求
_cache: Dict[str, dict] = {}
_cache_date: Optional[date] = None
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (compatible; stockpush/1.0)',
    'Referer': 'http://fundf10.eastmoney.com/',
})

TIMEOUT = 15
RETRIES = 2


def _fetch_html(code: str) -> Optional[str]:
    """获取 fhsp 页面 HTML，含重试。"""
    url = f"http://fundf10.eastmoney.com/fhsp_{code}.html"
    for attempt in range(RETRIES + 1):
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < RETRIES:
                logger.debug("fhsp %s 第%d次失败: %s", code, attempt + 1, e)
                time.sleep(1)
            else:
                logger.warning("fhsp %s 获取失败(已重试%d次): %s", code, RETRIES, e)
    return None


def _parse_fhsp(html: str) -> Dict[str, List[dict]]:
    """从 HTML 解析拆分和分红记录。"""
    splits: List[dict] = []
    dividends: List[dict] = []

    # ── 拆分 ──
    # 只在包含"拆分折算日"表头的区域提取
    split_section = re.search(
        r'拆分折算日[\s\S]*?(?:分红送配公告|分红信息|</table>)', html
    )
    if split_section:
        rows = re.findall(
            r'<td[^>]*?>(\d{4}年)</td>\s*'
            r'<td[^>]*?>(\d{4}-\d{2}-\d{2})</td>\s*'
            r'<td[^>]*?>([^<]+)</td>\s*'
            r'<td[^>]*?>([^<]+)</td>',
            split_section.group(0),
        )
        for year, dt, stype, ratio in rows:
            splits.append({
                'year': year,
                'date': dt,
                'type': stype.strip(),
                'ratio': ratio.strip(),
            })

    # ── 分红 ──
    # 只在包含"权益登记日"表头的区域提取
    div_section = re.search(
        r'权益登记日[\s\S]*?(?:拆分详情|分红送配公告|分红信息|</table>)', html
    )
    if div_section:
        rows = re.findall(
            r'<td[^>]*?>(\d{4}年)</td>\s*'
            r'<td[^>]*?>(\d{4}-\d{2}-\d{2})</td>\s*'
            r'<td[^>]*?>(\d{4}-\d{2}-\d{2})</td>\s*'
            r'<td[^>]*?>([^<]+)</td>\s*'
            r'<td[^>]*?>(\d{4}-\d{2}-\d{2})</td>',
            div_section.group(0),
        )
        for year, reg, ex, per, pay in rows:
            dividends.append({
                'year': year,
                'reg_date': reg,
                'ex_date': ex,
                'per_share': per.strip(),
                'pay_date': pay,
            })

    return {'splits': splits, 'dividends': dividends}


def check_fund_events(code: str) -> Dict[str, Any]:
    """查询指定基金的拆分/分红事件。

    Args:
        code: 基金代码

    Returns:
        {
            'code': str,
            'name': str,
            'splits': [...],
            'dividends': [...],
            'has_today_split': bool,
            'has_today_dividend': bool,
            'today_events': [...],
            'error': str | None,
        }
    """
    global _cache, _cache_date
    today = date.today()

    # 缓存检查
    if _cache_date != today:
        _cache.clear()
        _cache_date = today
    elif code in _cache:
        return _cache[code]

    result: Dict[str, Any] = {
        'code': code,
        'name': code,
        'splits': [],
        'dividends': [],
        'has_today_split': False,
        'has_today_dividend': False,
        'today_events': [],
        'error': None,
    }

    html = _fetch_html(code)
    if html is None:
        result['error'] = '页面获取失败'
        _cache[code] = result
        return result

    # 解析名称
    name_match = re.search(r'<title>([^(]+)\(', html)
    if name_match:
        result['name'] = name_match.group(1).strip()

    # 解析拆分分红
    parsed = _parse_fhsp(html)
    result['splits'] = parsed['splits']
    result['dividends'] = parsed['dividends']

    today_str = today.strftime('%Y-%m-%d')

    # 检查今日事件
    for s in parsed['splits']:
        if s['date'] == today_str:
            result['has_today_split'] = True
            result['today_events'].append({
                'type': 'split',
                'date': s['date'],
                'split_type': s['type'],
                'ratio': s['ratio'],
            })

    for d in parsed['dividends']:
        if d['reg_date'] == today_str or d['ex_date'] == today_str:
            result['has_today_dividend'] = True
            result['today_events'].append({
                'type': 'dividend',
                'reg_date': d['reg_date'],
                'ex_date': d['ex_date'],
                'per_share': d['per_share'],
                'pay_date': d['pay_date'],
            })

    _cache[code] = result
    return result


def check_watchlist_fund_events(
    symbols: List[str],
    fund_codes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """批量检查自选股池中所有标的的拆分/分红事件。

    Args:
        symbols: 全部自选股代码
        fund_codes: 基金代码子集（None 时全部检查）

    Returns:
        有今日拆分或分红的标的信息列表
    """
    results: List[Dict[str, Any]] = []
    targets = fund_codes if fund_codes is not None else symbols

    for code in targets:
        try:
            event = check_fund_events(code)
            if event['error']:
                logger.debug("check_fund_events %s: %s", code, event['error'])
                continue
            if event['has_today_split'] or event['has_today_dividend']:
                results.append(event)
        except Exception as e:
            logger.warning("check_fund_events %s 异常: %s", code, e)

    return results

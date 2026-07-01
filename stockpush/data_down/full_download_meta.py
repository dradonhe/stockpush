"""
全量下载元数据管理
记录股票/基金的名称、代码、上次全量下载时间、最新分红日期

文件路径: services/data_down/full_download_meta.json
"""
import json
import os
from pathlib import Path
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class AssetMeta:
    """资产元数据"""
    code: str           # 证券代码
    name: str           # 证券名称
    type: str           # 'stock' 或 'fund'
    last_dividend_date: Optional[str] = None  # 最新分红日期 YYYY-MM-DD


@dataclass
class FullDownloadMeta:
    """全量下载元数据"""
    last_full_download: str                    # 最近全量下载日期 YYYY-MM-DD
    assets: List[AssetMeta]                   # 资产列表

    @staticmethod
    def get_meta_file_path() -> Path:
        """获取元数据文件路径"""
        # 优先使用环境变量指定的路径
        env_path = os.getenv('FULL_DOWNLOAD_META_PATH')
        if env_path:
            return Path(env_path)

        # 默认路径：services/data_down/full_download_meta.json
        current_dir = Path(__file__).parent
        return current_dir / 'full_download_meta.json'

    @classmethod
    def load(cls) -> 'FullDownloadMeta':
        """从文件加载元数据"""
        meta_file = cls.get_meta_file_path()

        if not meta_file.exists():
            return cls(last_full_download='', assets=[])

        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            assets = [AssetMeta(**a) for a in data.get('assets', [])]
            return cls(
                last_full_download=data.get('last_full_download', ''),
                assets=assets
            )
        except (json.JSONDecodeError, TypeError) as e:
            # 如果文件损坏或格式错误，返回空元数据
            return cls(last_full_download='', assets=[])

    def save(self):
        """保存元数据到文件"""
        meta_file = self.get_meta_file_path()
        meta_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'last_full_download': self.last_full_download,
            'assets': [asdict(a) for a in self.assets]
        }

        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def find_asset(self, code: str) -> Optional[AssetMeta]:
        """根据代码查找资产元数据"""
        for asset in self.assets:
            if asset.code == code:
                return asset
        return None

    def add_or_update_asset(self, code: str, name: str, asset_type: str,
                            dividend_date: Optional[str] = None):
        """添加或更新资产元数据"""
        existing = self.find_asset(code)
        if existing:
            existing.name = name
            existing.type = asset_type
            if dividend_date:
                existing.last_dividend_date = dividend_date
        else:
            self.assets.append(AssetMeta(
                code=code,
                name=name,
                type=asset_type,
                last_dividend_date=dividend_date
            ))

    def update_full_download_date(self, download_date: str = None):
        """更新全量下载日期"""
        self.last_full_download = download_date or date.today().strftime('%Y-%m-%d')


def check_dividend_update_needed(code: str, asset_type: str,
                                  latest_dividend_date: str) -> tuple:
    """
    检查是否需要重新全量下载（基于分红日期）

    Args:
        code: 证券代码
        asset_type: 'stock' 或 'fund'
        latest_dividend_date: 最新分红日期

    Returns:
        (需要更新, 原因信息)
    """
    meta = FullDownloadMeta.load()
    asset = meta.find_asset(code)

    if not asset:
        return True, "新资产"

    if latest_dividend_date and asset.last_dividend_date:
        if latest_dividend_date > asset.last_dividend_date:
            return True, f"分红日期更新: {asset.last_dividend_date} -> {latest_dividend_date}"

    return False, ""

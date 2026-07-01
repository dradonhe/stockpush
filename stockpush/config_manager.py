"""
环境变量与配置管理模块
负责.env文件的读写和环境变量管理
"""
import os
from pathlib import Path
from typing import Optional, Dict
from stockpush.log_manager import LogManager


class ConfigManager:
    """
    配置管理器
    提供.env文件的读写、环境变量的获取与设置
    """
    
    def __init__(self, env_file: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            env_file: .env文件路径，默认为项目根目录的.env
        """
        self.logger = LogManager().get_logger("ConfigManager")
        
        # 确定项目根目录（包含.env文件的目录）
        if env_file:
            self.env_file = Path(env_file)
        else:
            # 项目根目录（向上查找直到找到.venv目录的父目录）
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent  # src -> stock
            self.env_file = project_root / '.env'
        
        # 初始化时加载环境变量
        self._load_env()
    
    def _load_env(self):
        """从.env文件加载环境变量到os.environ"""
        if not self.env_file.exists():
            self.logger.warning(f".env文件不存在: {self.env_file}")
            return
        
        try:
            with open(self.env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if not line or line.startswith('#'):
                        continue
                    
                    # 解析键值对
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # 移除值的引号（如果有）
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        
                        # 设置到环境变量
                        os.environ[key] = value
            
            self.logger.info(f"成功加载环境变量: {self.env_file}")
        
        except Exception as e:
            self.logger.error(f"加载.env文件失败: {e}")
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        获取环境变量
        
        Args:
            key: 环境变量键名
            default: 默认值
        
        Returns:
            环境变量值或默认值
        """
        return os.environ.get(key, default)
    
    def set(self, key: str, value: str, persist: bool = False) -> bool:
        """
        设置环境变量
        
        Args:
            key: 环境变量键名
            value: 环境变量值
            persist: 是否持久化到.env文件
        
        Returns:
            是否设置成功
        """
        try:
            # 设置到当前进程
            os.environ[key] = value
            
            # 如果需要持久化
            if persist:
                self._save_to_env(key, value)
            
            self.logger.info(f"设置环境变量: {key}")
            return True
        
        except Exception as e:
            self.logger.error(f"设置环境变量失败: {e}")
            return False
    
    def _save_to_env(self, key: str, value: str):
        """
        保存环境变量到.env文件
        
        Args:
            key: 环境变量键名
            value: 环境变量值
        """
        # 读取现有内容
        existing_lines = []
        key_found = False
        
        if self.env_file.exists():
            with open(self.env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    # 如果找到同名键，更新它
                    if stripped and not stripped.startswith('#') and '=' in stripped:
                        existing_key = stripped.split('=', 1)[0].strip()
                        if existing_key == key:
                            existing_lines.append(f"{key}={value}\n")
                            key_found = True
                            continue
                    existing_lines.append(line)
        
        # 如果键不存在，追加到末尾
        if not key_found:
            existing_lines.append(f"{key}={value}\n")
        
        # 写回文件
        with open(self.env_file, 'w', encoding='utf-8') as f:
            f.writelines(existing_lines)
        
        self.logger.info(f"保存环境变量到.env: {key}")
    
    def get_all(self) -> Dict[str, str]:
        """
        获取所有环境变量
        
        Returns:
            环境变量字典
        """
        if not self.env_file.exists():
            return {}
        
        env_vars = {}
        try:
            with open(self.env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # 移除引号
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        
                        env_vars[key] = value
        
        except Exception as e:
            self.logger.error(f"读取.env文件失败: {e}")
        
        return env_vars
    
    def delete(self, key: str, persist: bool = False) -> bool:
        """
        删除环境变量
        
        Args:
            key: 环境变量键名
            persist: 是否从.env文件删除
        
        Returns:
            是否删除成功
        """
        try:
            # 从当前进程删除
            if key in os.environ:
                del os.environ[key]
            
            # 如果需要持久化删除
            if persist and self.env_file.exists():
                existing_lines = []
                with open(self.env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('#') and '=' in stripped:
                            existing_key = stripped.split('=', 1)[0].strip()
                            if existing_key == key:
                                continue  # 跳过要删除的键
                        existing_lines.append(line)
                
                # 写回文件
                with open(self.env_file, 'w', encoding='utf-8') as f:
                    f.writelines(existing_lines)
            
            self.logger.info(f"删除环境变量: {key}")
            return True
        
        except Exception as e:
            self.logger.error(f"删除环境变量失败: {e}")
            return False


# 全局单例
_config_manager = None

def get_config_manager() -> ConfigManager:
    """获取配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

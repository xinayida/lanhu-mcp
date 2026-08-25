"""蓝湖认证模块：从 ~/.lanhu/cookie 文件读取浏览器 Cookie 认证"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://lanhuapp.com"
COOKIE_FILE = Path.home() / ".lanhu/cookie"


class LanhuAuthError(Exception):
    """认证相关错误"""
    pass


class LanhuAuth:
    """
    蓝湖认证管理器。

    Cookie 单一来源：~/.lanhu/cookie（格式 `session=...; user_token=...`，
    权限 600）。由 scripts/refresh_cookie.py 维护；lanhu_set_cookie 手动设置的
    值也会写回该文件。请求遇到认证失败时可调 reload() 重读文件。
    """

    def __init__(self) -> None:
        self._cookie: Optional[str] = None
        self._load()
        self._headers: dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Referer": "https://lanhuapp.com/web/",
            "Origin": "https://lanhuapp.com",
            "Accept": "application/json, text/plain, */*",
        }

    # ────────────────────── Cookie 文件读写 ──────────────────────

    def _load(self) -> bool:
        """从文件加载 Cookie。返回是否有变化（文件缺失/内容相同返回 False）"""
        try:
            value = COOKIE_FILE.read_text().strip()
        except FileNotFoundError:
            return False
        except OSError as e:
            logger.warning(f"读取 {COOKIE_FILE} 失败: {e}")
            return False
        if value and value != self._cookie:
            self._cookie = value
            logger.info("已从 %s 加载 Cookie", COOKIE_FILE)
            return True
        return False

    def reload(self) -> bool:
        """重读 Cookie 文件（refresh_cookie.py 更新后调用）。返回是否有变化"""
        return self._load()

    def set_cookie(self, cookie: str) -> None:
        """手动设置 Cookie 并写回文件（lanhu_set_cookie 工具入口）"""
        self._cookie = cookie.strip()
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(self._cookie + "\n")
        COOKIE_FILE.chmod(0o600)
        logger.info("已更新 Cookie 并写入 %s", COOKIE_FILE)

    # ────────────────────── 构建请求头 ──────────────────────────

    def get_headers(self) -> dict[str, str]:
        headers = dict(self._headers)
        if self._cookie:
            headers["Cookie"] = self._cookie
            # webapp 会带 authorization: Basic base64(user_token + ":")，一并模拟
            user_token = self.get_cookies().get("user_token")
            if user_token:
                basic = base64.b64encode(f"{user_token}:".encode()).decode()
                headers["Authorization"] = f"Basic {basic}"
        return headers

    def get_cookies(self) -> dict[str, str]:
        """将 cookie 字符串解析为字典"""
        if not self._cookie:
            return {}
        result: dict[str, str] = {}
        for part in self._cookie.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, val = part.partition("=")
                result[key.strip()] = val.strip()
        return result

    @property
    def is_authenticated(self) -> bool:
        return bool(self._cookie)

    def __repr__(self) -> str:
        if self._cookie:
            return f"LanhuAuth(cookie={self._cookie[:30]!r}...)"
        return "LanhuAuth(unauthenticated)"

#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.40"]
# ///
"""蓝湖 Cookie 自动刷新。

用专属 Chrome profile（~/.lanhu/profile）保存登录态：
- 已登录：无头访问蓝湖，把最新 Cookie 写入 ~/.lanhu/cookie，退出。
- 登录态失效：弹出浏览器窗口，等用户人工登录一次（短信/验证码），
  登录成功后自动保存 Cookie。

用法：uv run refresh_cookie.py [--headless-only]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / ".lanhu/profile"
COOKIE_FILE = Path.home() / ".lanhu/cookie"
CHECK_EXPR = (
    "fetch('/api/account/user_teams', {credentials: 'include'})"
    ".then(r => r.text()).catch(() => '')"
)
LOGIN_TIMEOUT_S = 600  # 人工登录等待上限
POLL_INTERVAL_S = 3


def _launch(p, headless: bool):
    return p.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",  # 复用系统已装的 Google Chrome，无需下载浏览器
        headless=headless,
        viewport={"width": 1280, "height": 900},
    )


def _logged_in(page) -> bool:
    try:
        text = page.evaluate(CHECK_EXPR)
    except Exception:
        return False
    return '"00000"' in (text or "")


def _save_cookies(context) -> bool:
    cookies = {c["name"]: c["value"] for c in context.cookies("https://lanhuapp.com")}
    session = cookies.get("session")
    user_token = cookies.get("user_token")
    if not session or not user_token:
        return False
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(f"session={session}; user_token={user_token}\n")
    COOKIE_FILE.chmod(0o600)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headless-only", action="store_true",
        help="只做无头刷新；需要人工登录时直接报错退出（适合定时任务）",
    )
    args = parser.parse_args()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # ── 第一阶段：无头检查并续期 ──────────────────────────────
    with sync_playwright() as p:
        context = _launch(p, headless=True)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://lanhuapp.com/dashboard/", wait_until="domcontentloaded")
        ok = _logged_in(page)
        saved = _save_cookies(context) if ok else False
        context.close()

    if saved:
        print(f"✓ Cookie 已刷新并写入 {COOKIE_FILE}")
        return 0

    if args.headless_only:
        print("✗ 登录态失效且指定了 --headless-only，未更新 Cookie", file=sys.stderr)
        return 1

    # ── 第二阶段：登录态失效 → 弹窗人工登录 ──────────────────
    print("登录态已失效，正在打开浏览器，请人工登录蓝湖（最多等 10 分钟）...")
    with sync_playwright() as p:
        context = _launch(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            "https://lanhuapp.com/",
            wait_until="domcontentloaded",  # "load" 会被挂起的统计脚本拖超时
            timeout=60000,
        )
        deadline = time.time() + LOGIN_TIMEOUT_S
        logged = False
        closed_polls = 0
        reason = "超时（10 分钟内未完成登录）"
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL_S)
            try:
                if _logged_in(page):
                    logged = True
                    break
                if not context.pages:  # 页面全关了（导航瞬间可能短暂为空，连续两次才算）
                    closed_polls += 1
                    if closed_polls >= 2:
                        reason = "浏览器窗口被关闭"
                        break
                else:
                    closed_polls = 0
            except Exception:
                continue
        if logged and _save_cookies(context):
            print(f"✓ 登录成功，Cookie 已保存到 {COOKIE_FILE}")
            ret = 0
        else:
            print(f"✗ 未完成登录（{reason}），Cookie 未更新", file=sys.stderr)
            ret = 1
        context.close()
        return ret


if __name__ == "__main__":
    sys.exit(main())

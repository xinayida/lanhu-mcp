"""蓝湖 MCP Server 主入口（基于 mcp 2.0 MCPServer 高层 API）"""

from __future__ import annotations

import functools
import logging
import os
import sys
from typing import Annotated, Any, Callable, Optional, TypeVar

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import __version__
from .auth import LanhuAuth, LanhuAuthError
from .client import LanhuAPIError, LanhuClient
from .models import LanhuAsset

load_dotenv()

# 日志输出到 stderr（stdio 模式下 stdout 被协议占用）
logging.basicConfig(
    level=getattr(logging, os.getenv("LANHU_LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("lanhu_mcp")

mcp = MCPServer(
    "lanhu-mcp",
    version=__version__,
    instructions=(
        "蓝湖设计稿 MCP。典型流程：lanhu_set_cookie 认证 → lanhu_get_teams → "
        "lanhu_get_projects(team_id) → lanhu_get_screens(project_id, team_id) → "
        "lanhu_get_annotations(project_id, image_id, team_id) 读取标注 → "
        "lanhu_download_asset 下载切图。"
    ),
)

_auth = LanhuAuth()
_client = LanhuClient(_auth)


# ─────────────────────── 通用错误处理 ───────────────────────────

F = TypeVar("F", bound=Callable[..., Any])


def _lanhu_errors(fn: F) -> F:
    """
    统一把蓝湖业务异常转为 ToolError。
    MCP 协议层会将其转换为 isError=true 的可读结果返回给客户端。
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except LanhuAuthError as e:
            raise ToolError(f"认证错误: {e}") from e
        except LanhuAPIError as e:
            raise ToolError(f"蓝湖 API 错误 (code={e.code}): {e}") from e

    return wrapper  # type: ignore[return-value]


def _ensure_auth() -> None:
    if not _auth.is_authenticated:
        raise LanhuAuthError(
            "尚未认证（~/.lanhu/cookie 不存在）。请运行 "
            "uv run /Users/wangwei/.gemini/antigravity/scratch/lanhu-mcp/scripts/refresh_cookie.py "
            "生成 Cookie，或调用 lanhu_set_cookie 手动设置。"
        )


# ─────────────────────── 工具：认证 ────────────────────────────


@mcp.tool()
@_lanhu_errors
async def lanhu_set_cookie(
    cookie: Annotated[
        str,
        Field(
            description=(
                "浏览器 Cookie 字符串，必须包含 session 和 user_token 两项，"
                "例如: session=.eJy...; user_token=eyJ..."
            )
        ),
    ],
) -> dict:
    """设置蓝湖认证 Cookie（并持久化到 ~/.lanhu/cookie）。

    一般无需手动调用：Cookie 文件由 scripts/refresh_cookie.py 自动维护，
    MCP 启动时自动读取。仅在自动刷新不可用时，才需要从浏览器手动复制：
    DevTools → Network → 任一 lanhuapp.com 请求 → Request Headers →
    复制完整 Cookie 头（须含 session 和 user_token）→ 传给本工具。
    设置后可调用 lanhu_get_teams 验证是否生效。
    """
    _auth.set_cookie(cookie)
    return {
        "success": True,
        "message": "Cookie 已设置。请调用 lanhu_get_teams 验证是否生效。",
    }


# ─────────────────────── 工具：团队 & 项目 ──────────────────────


@mcp.tool()
@_lanhu_errors
async def lanhu_get_teams() -> list[dict]:
    """获取当前登录用户所在的团队列表。也可用于验证认证是否有效。"""
    _ensure_auth()
    teams = await _client.get_teams()
    return [t.model_dump() for t in teams]


@mcp.tool()
@_lanhu_errors
async def lanhu_get_projects(
    team_id: Annotated[str, Field(description="团队 ID（从 lanhu_get_teams 获取）")],
) -> list[dict]:
    """获取团队下的设计项目列表。"""
    _ensure_auth()
    projects = await _client.get_projects(team_id)
    return [p.model_dump() for p in projects]


@mcp.tool()
@_lanhu_errors
async def lanhu_search_projects(
    team_id: Annotated[str, Field(description="团队 ID（从 lanhu_get_teams 获取）")],
    keyword: Annotated[str, Field(description="搜索关键词")],
) -> list[dict]:
    """在团队下按名称关键词搜索项目。"""
    _ensure_auth()
    projects = await _client.search_projects(team_id, keyword)
    return [p.model_dump() for p in projects]


# ─────────────────────── 工具：设计图 & 标注 ────────────────────


@mcp.tool()
@_lanhu_errors
async def lanhu_get_screens(
    project_id: Annotated[str, Field(description="项目 ID（从 lanhu_get_projects 获取）")],
    team_id: Annotated[str, Field(description="团队 ID")],
) -> list[dict]:
    """获取指定项目下的所有设计图（画板）列表，返回缩略图与尺寸信息。"""
    _ensure_auth()
    screens = await _client.get_screens(project_id, team_id)
    return [_screen_summary(s) for s in screens]


@mcp.tool()
@_lanhu_errors
async def lanhu_get_annotations(
    project_id: Annotated[str, Field(description="项目 ID")],
    image_id: Annotated[str, Field(description="设计图 ID（从 lanhu_get_screens 获取）")],
    team_id: Annotated[str, Field(description="团队 ID")],
) -> dict:
    """获取单张设计图的完整标注数据（最核心的工具）。

    返回内容包含：
    - 所有图层的树形结构（位置、尺寸、颜色、字体、行高、圆角、阴影、边框等）
    - 文本图层的文字内容与字体样式
    - 可下载的切图/图标列表（含 download_url）
    - 画板尺寸与缩略图
    """
    _ensure_auth()
    screen = await _client.get_annotations(project_id, image_id, team_id)
    return _screen_full(screen)


@mcp.tool()
@_lanhu_errors
async def lanhu_search_images(
    project_id: Annotated[str, Field(description="项目 ID")],
    team_id: Annotated[str, Field(description="团队 ID")],
    keyword: Annotated[str, Field(description="搜索关键词")],
) -> list[dict]:
    """在指定项目中按名称关键词搜索设计图。"""
    _ensure_auth()
    screens = await _client.search_images(project_id, team_id, keyword)
    return [_screen_summary(s) for s in screens]


# ─────────────────────── 工具：资源下载 ─────────────────────────


@mcp.tool()
@_lanhu_errors
async def lanhu_get_assets(
    project_id: Annotated[str, Field(description="项目 ID")],
    image_id: Annotated[str, Field(description="设计图 ID")],
    team_id: Annotated[str, Field(description="团队 ID")],
) -> list[dict]:
    """获取设计图中所有可下载的切图/图标资源列表（含 svg/png 直链）。"""
    _ensure_auth()
    assets = await _client.get_assets(project_id, image_id, team_id)
    return [a.model_dump() for a in assets]


@mcp.tool()
@_lanhu_errors
async def lanhu_download_asset(
    asset_id: Annotated[str, Field(description="资源 ID（从 lanhu_get_assets 获取）")],
    asset_name: Annotated[str, Field(description="资源名称，用作文件名")],
    download_url: Annotated[str, Field(description="下载链接（从 lanhu_get_assets 获取）")],
    format: Annotated[str, Field(description="文件格式：webp/svg/png（位图切图默认推荐 webp）")] = "webp",
    save_dir: Annotated[Optional[str], Field(description="保存目录（可选，默认 ~/Downloads/lanhu_assets）")] = None,
) -> dict:
    """下载指定的切图/图标到本地文件（位图默认自动转为 WebP 格式），返回保存路径。

    需要先调用 lanhu_get_assets 获取资源的 download_url 等信息。
    """
    _ensure_auth()
    asset = LanhuAsset(
        id=asset_id,
        name=asset_name,
        download_url=download_url,
        format=format,
    )
    file_path = await _client.download_asset(asset, save_dir)
    return {"success": True, "file_path": file_path, "message": f"已下载到: {file_path}"}


# ─────────────────────── 辅助函数 ──────────────────────────────


def _screen_summary(screen: Any) -> dict:
    """设计图摘要（不含图层详情）"""
    return {
        "id": screen.id,
        "name": screen.name,
        "width": screen.width,
        "height": screen.height,
        "thumbnail_url": screen.thumbnail_url,
        "project_id": screen.project_id,
    }


def _screen_full(screen: Any) -> dict:
    """设计图完整数据（含标注）"""

    def layer_to_dict(layer: Any) -> dict:
        d: dict = {
            "id": layer.id,
            "name": layer.name,
            "type": layer.type,
            "opacity": layer.opacity,
            "visible": layer.visible,
        }
        if layer.bounds:
            d["bounds"] = {
                "x": layer.bounds.x,
                "y": layer.bounds.y,
                "width": layer.bounds.width,
                "height": layer.bounds.height,
            }
        if layer.border_radius is not None:
            d["border_radius"] = layer.border_radius
        if layer.border_radii:
            d["border_radii"] = layer.border_radii
        if layer.text_content:
            d["text"] = layer.text_content
        if layer.font:
            font = layer.font
            font_dict: dict = {}
            if font.size is not None:
                font_dict["size"] = font.size
            if font.weight:
                font_dict["weight"] = font.weight
            if font.family:
                font_dict["family"] = font.family
            if font.line_height is not None:
                font_dict["line_height"] = font.line_height
            if font.letter_spacing is not None:
                font_dict["letter_spacing"] = font.letter_spacing
            if font.text_align:
                font_dict["text_align"] = font.text_align
            if font.color:
                font_dict["color"] = font.color.to_hex()
                font_dict["color_rgba"] = font.color.to_rgba()
                if font.color.a < 1.0:
                    font_dict["opacity"] = font.color.a
            if font.color_name or (font.color and font.color.name):
                font_dict["color_name"] = font.color_name or font.color.name
            if font.spans and len(font.spans) > 1:
                font_dict["spans"] = [
                    {
                        k: v
                        for k, v in {
                            "text": s.text,
                            "size": s.size,
                            "weight": s.weight,
                            "family": s.family,
                            "color": s.color.to_hex() if s.color else None,
                            "color_rgba": s.color.to_rgba() if s.color else None,
                        }.items()
                        if v is not None
                    }
                    for s in font.spans
                ]
            d["font"] = font_dict
        if layer.fills:
            fills_out = []
            for f in layer.fills:
                f_dict: dict = {
                    "type": f.type,
                    "opacity": f.opacity,
                }
                if f.color:
                    f_dict["color"] = f.color.to_hex()
                    f_dict["color_rgba"] = f.color.to_rgba()
                if f.color_name:
                    f_dict["color_name"] = f.color_name
                if f.gradient:
                    f_dict["gradient"] = {
                        "type": f.gradient.type,
                        "angle": f.gradient.angle,
                        "css": f.gradient.to_css(),
                        "stops": [
                            {
                                "position": s.position,
                                "color": s.color.to_hex() if s.color else None,
                                "color_rgba": s.color.to_rgba() if s.color else None,
                            }
                            for s in f.gradient.stops
                        ],
                    }
                fills_out.append(f_dict)
            d["fills"] = fills_out
        if layer.borders:
            borders_out = []
            for b in layer.borders:
                b_dict: dict = {
                    "width": b.width,
                    "style": b.style,
                    "position": b.position,
                }
                if b.color:
                    b_dict["color"] = b.color.to_hex()
                    b_dict["color_rgba"] = b.color.to_rgba()
                if b.color_name:
                    b_dict["color_name"] = b.color_name
                b_dict["css"] = b.to_css()
                borders_out.append(b_dict)
            d["borders"] = borders_out
        if layer.shadows:
            shadows_out = []
            for s in layer.shadows:
                s_dict: dict = {
                    "x": s.x,
                    "y": s.y,
                    "blur": s.blur,
                    "spread": s.spread,
                }
                if s.color:
                    s_dict["color"] = s.color.to_hex()
                    s_dict["color_rgba"] = s.color.to_rgba()
                if s.inner:
                    s_dict["inner"] = True
                s_dict["css"] = s.to_css()
                shadows_out.append(s_dict)
            d["shadows"] = shadows_out
        if layer.css:
            d["css"] = layer.css
        if layer.children:
            d["children"] = [layer_to_dict(c) for c in layer.children]
        return d

    return {
        "id": screen.id,
        "name": screen.name,
        "width": screen.width,
        "height": screen.height,
        "thumbnail_url": screen.thumbnail_url,
        "layers": [layer_to_dict(l) for l in screen.layers],
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "format": a.format,
                "width": a.width,
                "height": a.height,
                "download_url": a.download_url,
            }
            for a in screen.assets
        ],
    }


# ─────────────────────── 入口 ──────────────────────────────────


def main() -> None:
    """MCP Server 启动入口（stdio 模式）"""
    logger.info("蓝湖 MCP Server 启动 (stdio)...")
    if _auth.is_authenticated:
        logger.info("已从环境变量加载认证信息")
    else:
        logger.info("未检测到认证信息，请在对话中调用 lanhu_set_cookie 进行认证")
    mcp.run()


if __name__ == "__main__":
    main()

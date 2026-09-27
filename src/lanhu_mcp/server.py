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
from .url_parser import parse_lanhu_url

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
        "蓝湖设计稿与原型文档 MCP。最快捷方式：直接调用 lanhu_inspect_url(url) 查看任意蓝湖页面、画板或 Axure 原型链接；"
        "设计稿流程：lanhu_set_cookie 认证 → lanhu_get_screens → lanhu_get_annotations 读取标注 → lanhu_download_asset 下载切图；"
        "原型/PRD 流程：lanhu_list_product_documents → lanhu_get_pages 获取页面目录 → lanhu_get_page_content 提取需求说明与便签。"
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


# ─────────────────────── 工具：快捷 URL 统一查看 ────────────────
@mcp.tool()
@_lanhu_errors
async def lanhu_inspect_url(
    url: Annotated[
        str,
        Field(
            description=(
                "任意蓝湖页面链接（如项目画板 stage 链接、单图详情 detailDetach 链接、"
                "原型文档 product 链接、或分享邀请 invite 链接）。"
                "自动识别类型并返回画板列表、完整图层标注或解析结果。"
            )
        ),
    ],
) -> dict:
    """智能解析蓝湖 URL 并查看内容。最省心的统一入口。

    支持场景：
    - 输入单图画板链接：自动返回完整标注、尺寸、CSS 属性及切图资源；
    - 输入项目画板列表链接：自动返回所有设计图画板列表与缩略图；
    - 输入分享/邀请短链：自动调用原生 API 解析底层真实项目与链接；
    - 输入原型文档链接：识别 Axure 文档标识并给出引导。
    """
    _ensure_auth()
    return await _client.inspect_url(url)


# ─────────────────────── 工具：设计图 & 标注 ────────────────────


@mcp.tool()
@_lanhu_errors
async def lanhu_get_screens(
    project_id: Annotated[Optional[str], Field(description="项目 ID（若提供 url 则可选）")] = None,
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    url: Annotated[Optional[str], Field(description="蓝湖项目画板链接（例如 https://lanhuapp.com/web/#/item/project/stage?tid=xxx&pid=xxx，提供时自动提取参数）")] = None,
) -> list[dict]:
    """获取指定项目下的所有设计图（画板）列表，返回缩略图与尺寸信息。支持直接传入蓝湖链接。"""
    _ensure_auth()
    if url:
        parsed = parse_lanhu_url(url)
        project_id = project_id or parsed.project_id
        team_id = team_id or parsed.team_id
    if not project_id:
        raise ToolError("缺少 project_id 参数，请提供 project_id 或传入包含 pid 的蓝湖链接")
    screens = await _client.get_screens(project_id, team_id)
    return [_screen_summary(s) for s in screens]


@mcp.tool()
@_lanhu_errors
async def lanhu_get_annotations(
    project_id: Annotated[Optional[str], Field(description="项目 ID（若提供 url 则可选）")] = None,
    image_id: Annotated[Optional[str], Field(description="设计图 ID（若提供 url 则可选）")] = None,
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    url: Annotated[Optional[str], Field(description="蓝湖单图画板链接（例如 https://lanhuapp.com/web/#/item/project/detailDetach?pid=xxx&image_id=xxx，提供时自动提取参数）")] = None,
) -> dict:
    """获取单张设计图的完整标注数据（最核心的工具）。支持直接传入蓝湖单图链接。

    返回内容包含：
    - 所有图层的树形结构（位置、尺寸、颜色、字体、行高、圆角、阴影、边框等）
    - 文本图层的文字内容与字体样式
    - 可下载的切图/图标列表（含 download_url）
    - 画板尺寸、超大图安全标识与缩略图
    """
    _ensure_auth()
    if url:
        parsed = parse_lanhu_url(url)
        project_id = project_id or parsed.project_id
        image_id = image_id or parsed.image_id
        team_id = team_id or parsed.team_id
    if not project_id or not image_id:
        raise ToolError("缺少 project_id 或 image_id 参数，请提供对应 ID 或传入包含 pid 与 image_id 的蓝湖链接")
    screen = await _client.get_annotations(project_id, image_id, team_id)
    return _screen_full(screen)


@mcp.tool()
@_lanhu_errors
async def lanhu_search_images(
    project_id: Annotated[str, Field(description="项目 ID")],
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    keyword: Annotated[str, Field(description="搜索关键词")] = "",
) -> list[dict]:
    """在指定项目中按名称关键词搜索设计图。"""
    _ensure_auth()
    screens = await _client.search_images(project_id, team_id, keyword)
    return [_screen_summary(s) for s in screens]


# ─────────────────────── 工具：资源下载 ─────────────────────────


@mcp.tool()
@_lanhu_errors
async def lanhu_get_assets(
    project_id: Annotated[Optional[str], Field(description="项目 ID（若提供 url 则可选）")] = None,
    image_id: Annotated[Optional[str], Field(description="设计图 ID（若提供 url 则可选）")] = None,
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    url: Annotated[Optional[str], Field(description="蓝湖单图链接（提供时自动提取参数）")] = None,
) -> list[dict]:
    """获取设计图中所有可下载的切图/图标资源列表（矢量图为 svg，位图切图统一为 webp）。支持直接传入蓝湖链接。"""
    _ensure_auth()
    if url:
        parsed = parse_lanhu_url(url)
        project_id = project_id or parsed.project_id
        image_id = image_id or parsed.image_id
        team_id = team_id or parsed.team_id
    if not project_id or not image_id:
        raise ToolError("缺少 project_id 或 image_id 参数，请提供对应 ID 或传入包含 pid 与 image_id 的蓝湖链接")
    assets = await _client.get_assets(project_id, image_id, team_id)
    return [a.model_dump() for a in assets]


@mcp.tool()
@_lanhu_errors
async def lanhu_download_asset(
    asset_id: Annotated[str, Field(description="资源 ID（从 lanhu_get_assets 获取）")],
    asset_name: Annotated[str, Field(description="资源名称，用作文件名")],
    download_url: Annotated[str, Field(description="下载链接（从 lanhu_get_assets 获取）")],
    format: Annotated[str, Field(description="文件格式：webp 或 svg（位图切图统一自动转换为 webp 保存，矢量图标为 svg）")] = "webp",
    save_dir: Annotated[Optional[str], Field(description="保存目录（可选，默认 ~/Downloads/lanhu_assets）")] = None,
) -> dict:
    """下载指定的切图/图标到本地文件（所有位图切图统一自动转换为 WebP 格式保存，矢量图标保持 SVG 格式），返回保存路径。

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


# ─────────────────────── 工具：PRD / 原型文档 (Axure) ──────────


@mcp.tool()
@_lanhu_errors
async def lanhu_list_product_documents(
    project_id: Annotated[Optional[str], Field(description="项目 ID（若提供 url 则可选）")] = None,
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    url: Annotated[Optional[str], Field(description="蓝湖项目链接或文档链接（提供时自动提取 project_id）")] = None,
) -> list[dict]:
    """获取项目下的所有产品文档/Axure 原型文档列表。支持直接传入蓝湖链接。"""
    _ensure_auth()
    if url:
        parsed = parse_lanhu_url(url)
        project_id = project_id or parsed.project_id
        team_id = team_id or parsed.team_id
    if not project_id:
        raise ToolError("缺少 project_id 参数，请提供 project_id 或传入包含 pid 的蓝湖链接")
    docs = await _client.get_product_documents(project_id, team_id)
    return [d.model_dump() for d in docs]


@mcp.tool()
@_lanhu_errors
async def lanhu_get_pages(
    project_id: Annotated[Optional[str], Field(description="项目 ID（若提供 url 则可选）")] = None,
    doc_id: Annotated[Optional[str], Field(description="Axure 原型文档 ID（若提供 url 则可选）")] = None,
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    url: Annotated[Optional[str], Field(description="蓝湖 Axure 原型文档链接（如 productDoc 链接，提供时自动提取 pid 和 doc_id）")] = None,
) -> dict:
    """获取 Axure 原型的页面目录树 (Sitemap) 及清单。支持直接传入原型链接。"""
    _ensure_auth()
    if url:
        parsed = parse_lanhu_url(url)
        project_id = project_id or parsed.project_id
        doc_id = doc_id or parsed.doc_id
        team_id = team_id or parsed.team_id
    if not project_id or not doc_id:
        raise ToolError("缺少 project_id 或 doc_id 参数，请提供对应 ID 或传入包含 pid 与 doc_id 的原型链接")
    result = await _client.get_axure_sitemap(project_id, doc_id, team_id)
    return {
        "doc_id": result.get("doc_id"),
        "doc_name": result.get("doc_name"),
        "project_id": result.get("project_id"),
        "version": result.get("version"),
        "page_count": result.get("page_count"),
        "pages": result.get("pages"),
    }


@mcp.tool()
@_lanhu_errors
async def lanhu_get_page_content(
    page_name: Annotated[str, Field(description="页面名称或文件名（例如 '登录页' 或 '登录页.html'）")],
    project_id: Annotated[Optional[str], Field(description="项目 ID（若提供 url 则可选）")] = None,
    doc_id: Annotated[Optional[str], Field(description="Axure 原型文档 ID（若提供 url 则可选）")] = None,
    team_id: Annotated[Optional[str], Field(description="团队 ID（可选）")] = None,
    url: Annotated[Optional[str], Field(description="蓝湖 Axure 原型文档链接（提供时自动提取 pid 和 doc_id）")] = None,
) -> dict:
    """提取 Axure 页面中的需求说明文本、便签 (annotations) 和备注 (notes)。支持直接传入原型链接。"""
    _ensure_auth()
    if url:
        parsed = parse_lanhu_url(url)
        project_id = project_id or parsed.project_id
        doc_id = doc_id or parsed.doc_id
        team_id = team_id or parsed.team_id
    if not project_id or not doc_id:
        raise ToolError("缺少 project_id 或 doc_id 参数，请提供对应 ID 或传入包含 pid 与 doc_id 的原型链接")
    page = await _client.get_axure_page_content(project_id, doc_id, page_name, team_id)
    return page.model_dump()


# ─────────────────────── 辅助函数 ──────────────────────────────


def _screen_summary(screen: Any) -> dict:
    """设计图摘要（不含图层详情）"""
    return {
        "id": screen.id,
        "name": screen.name,
        "width": screen.width,
        "height": screen.height,
        "is_oversized": getattr(screen, "is_oversized", False),
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
        "is_oversized": getattr(screen, "is_oversized", False),
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

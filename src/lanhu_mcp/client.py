"""蓝湖 API 客户端 — 封装所有 HTTP 请求，解析返回数据

API 契约（2026-08 逆向自 lanhuapp.com webapp）：
- 认证：Cookie `session=...; user_token=...`（session 必需）
- 响应包络：`code` 为 "00000"/0 表示成功，数据在 `result` 或 `data` 字段
- 图层标注数据：image 元信息中最新版本的 `json_url` 指向公开 OSS JSON
"""

from __future__ import annotations

import html
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from .auth import LanhuAuth, LanhuAuthError
from .models import (
    LanhuAsset,
    LanhuAxurePage,
    LanhuBorder,
    LanhuBounds,
    LanhuColor,
    LanhuDesignTokens,
    LanhuFill,
    LanhuFont,
    LanhuGradient,
    LanhuGradientStop,
    LanhuLayer,
    LanhuLayoutNode,
    LanhuProductDoc,
    LanhuProject,
    LanhuScreen,
    LanhuShadow,
    LanhuTeam,
    LanhuTextSpan,
)
from .url_parser import parse_lanhu_url

logger = logging.getLogger(__name__)

BASE_URL = "https://lanhuapp.com"


class LanhuAPIError(Exception):
    """API 调用错误"""

    def __init__(self, msg: str, code: int = -1, raw: Any = None):
        super().__init__(msg)
        self.code = code
        self.raw = raw


# ─────────────────────────── UTF-16 与 Axure 辅助函数 ─────────────


def slice_utf16_text(text: str, start: int, length: int) -> str:
    """根据 UTF-16 code unit 偏移与长度切片字符串，防止因 Emoji 等代理对产生偏移或断裂"""
    if not text or length <= 0 or start < 0:
        return ""
    raw_bytes = text.encode("utf-16-le")
    byte_start = start * 2
    byte_end = (start + length) * 2
    if byte_start >= len(raw_bytes):
        return ""
    slice_bytes = raw_bytes[byte_start:byte_end]
    return slice_bytes.decode("utf-16-le", errors="ignore")


def extract_axure_pages_from_sitemap(sitemap: dict) -> list[dict]:
    """从 Axure sitemap 树结构中提取所有页面列表（展平为一维列表）"""
    root_nodes = sitemap.get("rootNodes") or sitemap.get("pages") or []
    if isinstance(sitemap, list):
        root_nodes = sitemap

    pages: list[dict] = []

    def walk(nodes: list[dict], parent_folder: str = "根目录", path_prefix: str = "", level: int = 0) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            name = node.get("pageName") or node.get("name") or ""
            node_type = node.get("type") or "Wireframe"
            url = node.get("url") or ""
            children = node.get("children") or []
            current_path = f"{path_prefix}/{name}" if path_prefix else name

            if node_type == "Folder" or not url:
                # 文件夹节点
                walk(children, parent_folder=name, path_prefix=current_path, level=level + 1)
            else:
                # 页面节点
                pages.append({
                    "id": str(node.get("id") or ""),
                    "name": name,
                    "filename": url,
                    "type": node_type,
                    "level": level,
                    "folder": parent_folder,
                    "path": current_path,
                    "has_children": bool(children),
                })
                if children:
                    walk(children, parent_folder=name, path_prefix=current_path, level=level + 1)

    walk(root_nodes)
    return pages


def extract_axure_page_text(html_content: str) -> list[str]:
    """从 Axure 页面 HTML 中提取需求文本段落列表，自动清除标签并解码 HTML 实体"""
    if not html_content:
        return []

    # 优先匹配 class 包含 text 的容器（Axure 默认文本容器）
    pattern = re.compile(
        r'<div[^>]*class=["\'][^"\']*\btext\b[^"\']*["\'][^>]*>(.*?)</div>',
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(html_content)

    results: list[str] = []
    tag_cleaner = re.compile(r"<[^>]+>")

    for match in matches:
        cleaned = tag_cleaner.sub(" ", match)
        unescaped = html.unescape(cleaned)
        normalized = re.sub(r"[ \t]+", " ", unescaped).strip()
        if normalized:
            results.append(normalized)

    # 兜底：如果没匹配到带 text 类的 div，尝试提取所有 <p> 标签
    if not results:
        p_pattern = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
        for p in p_pattern.findall(html_content):
            cleaned = tag_cleaner.sub(" ", p)
            unescaped = html.unescape(cleaned)
            normalized = re.sub(r"\s+", " ", unescaped).strip()
            if normalized:
                results.append(normalized)

    return results


def parse_axure_data_js(js_content: str) -> dict:
    """解析 Axure 页面 data.js 脚本，提取页面便签 annotations、备注 notes 及组件 objects"""
    if not js_content:
        return {"name": "", "annotations": [], "notes": {}, "objects": []}

    first_brace = js_content.find("{")
    last_brace = js_content.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        return {"name": "", "annotations": [], "notes": {}, "objects": []}

    try:
        data = json.loads(js_content[first_brace : last_brace + 1])
    except Exception as e:
        logger.warning(f"解析 Axure data.js JSON 失败: {e}")
        return {"name": "", "annotations": [], "notes": {}, "objects": []}

    page = data.get("page") or {}
    page_name = page.get("name") or ""
    raw_annos = page.get("annotations") or []
    clean_annos: list[dict[str, Any]] = []

    for a in raw_annos:
        if not isinstance(a, dict):
            continue
        label = a.get("label") or a.get("name") or ""
        note = a.get("note") or a.get("注释") or a.get("说明") or a.get("content") or ""
        if not note:
            for k, v in a.items():
                if k not in ("fn", "label", "ownerId", "id") and isinstance(v, str):
                    note = v
                    break
        clean_annos.append({
            "label": label,
            "note": note,
            "owner_id": a.get("ownerId") or a.get("id"),
            "raw": a,
        })

    notes = page.get("notes") or {}
    diagram = page.get("diagram") or {}
    objects = diagram.get("objects") or []

    return {
        "name": page_name,
        "annotations": clean_annos,
        "notes": notes,
        "objects": objects,
    }


class LanhuClient:
    """蓝湖私有 API 客户端。所有方法均为 async。"""

    def __init__(self, auth: LanhuAuth) -> None:
        self.auth = auth
        self._timeout = float(os.getenv("LANHU_TIMEOUT", "30"))

    # ─────────────────────────── 内部工具 ────────────────────────

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE_URL,
            headers=self.auth.get_headers(),
            cookies=self.auth.get_cookies(),
            timeout=self._timeout,
            follow_redirects=True,
            trust_env=False,
        )

    async def _get(self, path: str, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json: dict | None = None) -> Any:
        return await self._request("POST", path, json=json)

    async def _request(
        self, method: str, path: str,
        params: dict | None = None, json: dict | None = None,
    ) -> Any:
        async with self._client() as client:
            try:
                resp = (
                    await client.get(path, params=params)
                    if method == "GET"
                    else await client.post(path, json=json)
                )
            except httpx.HTTPError as e:
                raise LanhuAPIError(f"网络请求失败 ({path}): {e}") from e
            try:
                return self._parse(resp)
            except LanhuAuthError:
                # Cookie 文件可能已被 refresh_cookie.py 更新，重读后重试一次
                if self.auth.reload():
                    logger.info("Cookie 文件已更新，重试请求")
                    return await self._request(method, path, params=params, json=json)
                raise

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        """解析蓝湖 API 响应。成功返回 result（无则 data），失败抛异常。"""
        try:
            data = resp.json()
        except Exception:
            text_head = resp.text[:200]
            # 认证失效时不返回 JSON 错误码，而是 200 + HTML 登录页
            if "<!DOCTYPE" in text_head.upper() or "<HTML" in text_head.upper():
                raise LanhuAuthError(
                    f"服务端返回了 HTML 页面而非 API 数据（HTTP {resp.status_code}），"
                    "通常是 Cookie 已过期。请运行 scripts/refresh_cookie.py 刷新 Cookie。"
                )
            raise LanhuAPIError(
                f"响应不是 JSON 格式，HTTP {resp.status_code}: {text_head}"
            )

        if not isinstance(data, dict):
            if resp.status_code >= 400:
                raise LanhuAPIError(f"API 请求失败 HTTP {resp.status_code}: {resp.text[:200]}")
            return data

        code = data.get("code", -1)
        if isinstance(code, str) and code.isdigit():
            code = int(code)

        # code=5 / 30001 表示未登录
        if code == 5 or code == 30001:
            raise LanhuAuthError(
                "未登录或认证已过期。请运行 "
                "uv run /Users/wangwei/.gemini/antigravity/scratch/lanhu-mcp/scripts/refresh_cookie.py "
                "刷新 Cookie（登录态真过期时会弹浏览器要求人工登录一次）。"
            )

        # "00000" / 0 表示成功
        if code == 0:
            if "result" in data:
                return data.get("result")
            return data.get("data")

        msg = data.get("msg") or data.get("message") or f"API 错误 code={code}"
        raise LanhuAPIError(msg, code=code, raw=data)

    # ─────────────────────────── 团队 ────────────────────────────

    async def get_teams(self) -> list[LanhuTeam]:
        """获取用户所在团队列表"""
        result = await self._get("/api/account/user_teams")
        if not result:
            return []

        teams = result if isinstance(result, list) else result.get("teams", [])
        out: list[LanhuTeam] = []
        for t in teams:
            role = t.get("role")
            if isinstance(role, dict):
                role = role.get("display")
            out.append(
                LanhuTeam(
                    id=str(t.get("team_id") or t.get("id") or ""),
                    name=t.get("team_name") or t.get("name") or "",
                    role=role,
                    member_count=t.get("member_num") or t.get("member_count"),
                )
            )
        return out

    # ─────────────────────────── 项目 ────────────────────────────

    async def get_projects(self, team_id: str) -> list[LanhuProject]:
        """获取团队下的设计项目列表（workbench 文件列表，过滤出设计项目）"""
        result = await self._post(
            "/workbench/api/workbench/abstractfile/list",
            json={"tenantId": team_id, "fid": "all"},
        )
        if not isinstance(result, list):
            return []

        out: list[LanhuProject] = []
        for p in result:
            if p.get("sourceType") != "dc_prj":  # 只要设计项目
                continue
            out.append(
                LanhuProject(
                    id=str(p.get("sourceId") or ""),
                    name=p.get("sourceName") or "",
                    cover_url=p.get("sourceThumbnail"),
                    team_id=team_id,
                    updated_at=str(p.get("updateTime") or ""),
                )
            )
        return out

    async def search_projects(self, team_id: str, keyword: str) -> list[LanhuProject]:
        """按名称关键词过滤团队项目"""
        projects = await self.get_projects(team_id)
        kw = keyword.lower()
        return [p for p in projects if kw in p.name.lower()]

    # ─────────────────────────── 设计图（Screens）────────────────

    async def get_screens(self, project_id: str, team_id: str | None = None) -> list[LanhuScreen]:
        """获取项目下所有设计图（画板）列表"""
        params: dict[str, Any] = {"project_id": project_id}
        if team_id:
            params["team_id"] = team_id
        result = await self._get(
            "/api/project/images",
            params=params,
        )
        images = (result or {}).get("images", []) if isinstance(result, dict) else []
        return [self._parse_screen_basic(img, project_id) for img in images]

    async def search_images(
        self, project_id: str, team_id: str | None = None, keyword: str = ""
    ) -> list[LanhuScreen]:
        """按名称关键词过滤设计图"""
        screens = await self.get_screens(project_id, team_id)
        kw = keyword.lower()
        return [s for s in screens if kw in s.name.lower()]

    def _parse_screen_basic(self, raw: dict, project_id: str) -> LanhuScreen:
        return LanhuScreen(
            id=str(raw.get("id") or ""),
            name=raw.get("name") or "",
            width=self._to_float(raw.get("width")),
            height=self._to_float(raw.get("height")),
            thumbnail_url=raw.get("url"),
            project_id=project_id,
        )

    # ─────────────────────────── 标注（Annotations）──────────────

    async def _fetch_dds(
        self, project_id: str, image_id: str, team_id: str | None = None
    ) -> tuple[LanhuScreen, dict]:
        """取设计图元信息 + 最新版本的图层 JSON（DDS）"""
        params: dict[str, Any] = {
            "image_id": image_id,
            "project_id": project_id,
            "dds_status": 1,
        }
        if team_id:
            params["team_id"] = team_id
        info = await self._get(
            "/api/project/image",
            params=params,
        )
        if not info:
            raise LanhuAPIError(f"获取设计图 {image_id} 的信息失败")

        screen = LanhuScreen(
            id=str(info.get("id") or image_id),
            name=info.get("name") or "",
            width=self._to_float(info.get("width")),
            height=self._to_float(info.get("height")),
            thumbnail_url=info.get("url"),
            project_id=project_id,
        )

        versions = info.get("versions") or []
        latest_id = info.get("latest_version")
        version = next((v for v in versions if v.get("id") == latest_id), None)
        if version is None and versions:
            version = versions[0]

        dds: dict = {}
        json_url = (version or {}).get("json_url")
        if json_url:
            async with self._client() as client:
                resp = await client.get(json_url)  # 公开 OSS，无需认证
                dds = resp.json()
        else:
            logger.warning(f"设计图 {image_id} 没有版本 JSON（可能是纯图片）")
        return screen, dds

    async def get_annotations(
        self, project_id: str, image_id: str, team_id: str | None = None
    ) -> LanhuScreen:
        """获取单张设计图的完整标注：图层树 + 切图资源"""
        screen, dds = await self._fetch_dds(project_id, image_id, team_id)
        if "artboard" in dds:
            # Figma 格式
            artboard = dds.get("artboard") or {}
            root_layer = self._parse_figma_layer(artboard)
            screen.layers = root_layer.children if root_layer.children else [root_layer]
            screen.assets = self._parse_figma_assets(artboard)
        else:
            # Sketch 格式
            nodes = dds.get("info") or []
            screen.layers = self._build_layers(nodes)
            screen.assets = self._parse_assets(nodes)
        return screen

    # ─────────────────────────── 图层解析 ────────────────────────

    def _parse_figma_layer(self, raw: dict) -> LanhuLayer:
        """Figma 图层节点 → LanhuLayer 递归解析"""
        style_raw = raw.get("style") or {}
        layer = LanhuLayer(
            id=str(raw.get("id") or ""),
            name=raw.get("name") or "",
            type=raw.get("type") or "unknown",
            opacity=float(style_raw.get("opacity") or raw.get("opacity") or 1.0),
            visible=bool(raw.get("visible", True) if "visible" in raw else raw.get("isVisible", True)),
        )

        frame = raw.get("frame") or raw.get("realFrame") or {}
        layer.bounds = LanhuBounds(
            x=float(frame.get("left") or raw.get("left") or 0),
            y=float(frame.get("top") or raw.get("top") or 0),
            width=float(frame.get("width") or raw.get("width") or 0),
            height=float(frame.get("height") or raw.get("height") or 0),
        )

        # 圆角
        radius = raw.get("radius") or raw.get("cornerRadius") or style_raw.get("cornerRadius")
        rect_radii = raw.get("rectangleCornerRadii") or style_raw.get("rectangleCornerRadii")
        if rect_radii and isinstance(rect_radii, list) and len(rect_radii) == 4:
            radii = [self._to_float(v) or 0.0 for v in rect_radii]
            if len(set(radii)) > 1:
                layer.border_radii = radii
                layer.border_radius = max(radii)
            elif radii:
                layer.border_radius = radii[0]
        elif isinstance(radius, dict):
            tl = self._to_float(radius.get("topLeft")) or 0.0
            tr = self._to_float(radius.get("topRight")) or 0.0
            br = self._to_float(radius.get("bottomRight")) or 0.0
            bl = self._to_float(radius.get("bottomLeft")) or 0.0
            radii = [tl, tr, br, bl]
            if len(set(radii)) > 1:
                layer.border_radii = radii
                layer.border_radius = max(radii)
            elif radii:
                layer.border_radius = radii[0]
        elif isinstance(radius, (int, float)):
            layer.border_radius = float(radius)
        elif isinstance(radius, list) and radius:
            radii = [self._to_float(v) or 0.0 for v in radius]
            if len(radii) == 4 and len(set(radii)) > 1:
                layer.border_radii = radii
                layer.border_radius = max(radii)
            elif radii:
                layer.border_radius = radii[0]

        # 文本
        text_raw = raw.get("text")
        characters = raw.get("characters") or (
            text_raw.get("value") if isinstance(text_raw, dict) else (text_raw if isinstance(text_raw, str) else None)
        )
        if characters:
            layer.text_content = characters

        fills_raw = style_raw.get("fills") or raw.get("fills") or []

        if layer.text_content or str(raw.get("type", "")).lower() in ("text", "type"):
            styles = text_raw.get("styles") or [] if isinstance(text_raw, dict) else []
            s0 = styles[0] if styles else (text_raw.get("style") if isinstance(text_raw, dict) else style_raw)
            if not isinstance(s0, dict):
                s0 = style_raw
            f_info = s0.get("font") if isinstance(s0.get("font"), dict) else s0

            family = (
                f_info.get("name")
                or f_info.get("family")
                or f_info.get("fontFamily")
                or f_info.get("postScriptName")
                or style_raw.get("fontFamily")
            )
            weight = self._normalize_font_weight(
                f_info.get("fontWeight") or f_info.get("weight") or f_info.get("type") or style_raw.get("fontWeight"),
                family or "",
            )
            size = self._to_float(f_info.get("size") or f_info.get("fontSize") or style_raw.get("fontSize"))

            lh = f_info.get("lineHeight") or f_info.get("lineHeightPx") or style_raw.get("lineHeight")
            line_height = self._to_float(lh.get("value")) if isinstance(lh, dict) else self._to_float(lh)

            ls = f_info.get("letterSpacing") or style_raw.get("letterSpacing")
            letter_spacing = self._to_float(ls.get("value")) if isinstance(ls, dict) else self._to_float(ls)

            color = self._parse_color(
                s0.get("color")
                or (text_raw.get("style", {}).get("color") if isinstance(text_raw, dict) else None)
                or style_raw.get("color")
            )
            if not color and fills_raw:
                color = self._parse_color(fills_raw[0].get("color") or fills_raw[0])

            align_raw = (
                f_info.get("align")
                or f_info.get("textAlignHorizontal")
                or f_info.get("textAlign")
                or style_raw.get("textAlignHorizontal")
            )
            text_align = _TEXT_ALIGN.get(align_raw, str(align_raw) if align_raw is not None else None)

            # 解析富文本 spans
            spans: list[LanhuTextSpan] = []
            for s in styles:
                if not isinstance(s, dict):
                    continue
                content = str(s.get("content") or s.get("value") or "")
                if not content and layer.text_content:
                    loc = s.get("location") if s.get("location") is not None else s.get("start")
                    length = s.get("length") if s.get("length") is not None else s.get("len")
                    if loc is not None and length is not None:
                        content = slice_utf16_text(layer.text_content, int(loc), int(length))
                sc = self._parse_color(s.get("color")) or color
                sf = s.get("font") if isinstance(s.get("font"), dict) else s
                s_family = sf.get("name") or sf.get("family") or family
                s_weight = self._normalize_font_weight(sf.get("fontWeight") or sf.get("weight"), s_family or "")
                spans.append(
                    LanhuTextSpan(
                        text=content,
                        size=self._to_float(sf.get("size") or sf.get("fontSize")) or size,
                        weight=s_weight,
                        family=s_family,
                        color=sc,
                        line_height=line_height,
                        letter_spacing=letter_spacing,
                    )
                )

            layer.font = LanhuFont(
                size=size,
                weight=weight,
                family=family,
                line_height=line_height,
                letter_spacing=letter_spacing,
                color=color,
                color_name=color.name if color else None,
                text_align=text_align,
                spans=spans,
            )

        # 填充解析
        fills: list[LanhuFill] = []
        for f in fills_raw:
            if not isinstance(f, dict):
                continue
            if f.get("visible") is False or f.get("isEnabled") is False:
                continue
            f_type = str(f.get("type") or "color").lower()
            f_opacity = float(f.get("opacity", 1.0))
            if "gradient" in f_type or "gradient" in f or "gradientStops" in f:
                g_obj = f.get("gradient") or f
                gradient = self._parse_gradient(g_obj, f_opacity)
                fills.append(
                    LanhuFill(
                        type="gradient",
                        gradient=gradient,
                        opacity=f_opacity,
                    )
                )
            else:
                c = self._parse_color(f.get("color") or f)
                fills.append(
                    LanhuFill(
                        type="solid",
                        color=c,
                        color_name=c.name if c else None,
                        opacity=f_opacity,
                    )
                )
        layer.fills = fills

        # 边框解析
        borders_raw = (
            style_raw.get("borders")
            or raw.get("borders")
            or style_raw.get("strokes")
            or raw.get("strokes")
            or []
        )
        borders: list[LanhuBorder] = []
        for b in borders_raw:
            if not isinstance(b, dict):
                continue
            if b.get("visible") is False or b.get("isEnabled") is False:
                continue
            b_pos_raw = b.get("lineAlignment") or b.get("position") or b.get("strokeAlign")
            b_pos = _BORDER_POSITION.get(b_pos_raw, str(b_pos_raw or "inside"))
            c = self._parse_color(b.get("color") or b)
            borders.append(
                LanhuBorder(
                    width=float(b.get("width") or b.get("thickness") or b.get("strokeWeight") or 0),
                    color=c,
                    color_name=c.name if c else None,
                    style=b.get("style") or "solid",
                    position=b_pos,
                )
            )
        layer.borders = borders

        # 阴影解析
        shadows_raw = (
            style_raw.get("shadows")
            or raw.get("shadows")
            or style_raw.get("effects")
            or raw.get("effects")
            or []
        )
        shadows: list[LanhuShadow] = []
        for s in shadows_raw:
            if not isinstance(s, dict):
                continue
            if s.get("visible") is False or s.get("isEnabled") is False:
                continue
            offset = s.get("offset") or {}
            x = float(s.get("offsetX") or s.get("x") or offset.get("x") or 0)
            y = float(s.get("offsetY") or s.get("y") or offset.get("y") or 0)
            blur = float(s.get("blurRadius") or s.get("blur") or s.get("radius") or 0)
            spread = float(s.get("spread") or 0)
            c = self._parse_color(s.get("color"))
            s_type = str(s.get("type", "")).upper()
            inner = bool(s.get("inner", False) or "INNER" in s_type)
            shadows.append(
                LanhuShadow(
                    x=x, y=y, blur=blur, spread=spread, color=c, inner=inner
                )
            )
        layer.shadows = shadows

        # 生成 CSS
        layer.css = self._generate_layer_css(layer)

        children_raw = raw.get("layers") or raw.get("children") or []
        layer.children = [self._parse_figma_layer(c) for c in children_raw if isinstance(c, dict)]
        return layer

    def _parse_figma_assets(self, root: dict) -> list[LanhuAsset]:
        """递归提取 Figma 中的切图资源"""
        out: list[LanhuAsset] = []

        def traverse(node: dict) -> None:
            img = node.get("image") or {}
            nid = str(node.get("id") or "")
            name = node.get("name") or nid or "asset"
            size = node.get("frame") or {}
            if img.get("svgUrl"):
                out.append(
                    LanhuAsset(
                        id=f"{nid}:svg",
                        name=name,
                        format="svg",
                        width=self._to_float(size.get("width")),
                        height=self._to_float(size.get("height")),
                        download_url=img["svgUrl"],
                    )
                )
            if img.get("imageUrl"):
                out.append(
                    LanhuAsset(
                        id=f"{nid}:webp",
                        name=name,
                        format="webp",
                        width=self._to_float(size.get("width")),
                        height=self._to_float(size.get("height")),
                        download_url=img["imageUrl"],
                    )
                )
            for c in node.get("layers") or []:
                if isinstance(c, dict):
                    traverse(c)

        traverse(root)
        return out

    def _build_layers(self, nodes: list[dict]) -> list[LanhuLayer]:
        """DDS 的 info[] 是扁平数组，通过 parentID 组装成树，按 index 排序"""
        layers: dict[str, tuple[LanhuLayer, int]] = {}
        for n in nodes:
            nid = str(n.get("id") or "")
            layers[nid] = (self._parse_dds_layer(n), int(n.get("index") or 0))

        roots: list[LanhuLayer] = []
        for n in nodes:
            nid = str(n.get("id") or "")
            layer, _ = layers[nid]
            parent = layers.get(str(n.get("parentID") or ""))
            if parent is not None:
                parent[0].children.append(layer)
            else:
                roots.append(layer)

        def sort_children(layer: LanhuLayer) -> None:
            order = {id(c): layers.get(c.id, (None, 0))[1] for c in layer.children}
            layer.children.sort(key=lambda c: order.get(id(c), 0))
            for c in layer.children:
                sort_children(c)

        for root in roots:
            sort_children(root)
        return roots

    def _parse_dds_layer(self, raw: dict) -> LanhuLayer:
        """DDS 图层节点 → LanhuLayer"""
        layer = LanhuLayer(
            id=str(raw.get("id") or ""),
            name=raw.get("name") or "",
            type=raw.get("type") or "unknown",
            opacity=float(raw.get("opacity", 100)) / 100.0,
            visible=bool(raw.get("isVisible", True)),
        )

        # 位置 & 尺寸（绝对坐标）
        layer.bounds = LanhuBounds(
            x=float(raw.get("left") or 0),
            y=float(raw.get("top") or 0),
            width=float(raw.get("width") or 0),
            height=float(raw.get("height") or 0),
        )

        # 圆角：radius 可能是数组，points[].cornerRadius 兜底
        radius = (
            raw.get("radius")
            or raw.get("radiuses")
            or raw.get("borderRadius")
            or raw.get("cornerRadius")
        )
        if isinstance(radius, list) and radius:
            radii = [self._to_float(v) or 0.0 for v in radius]
            if len(radii) == 4 and len(set(radii)) > 1:
                layer.border_radii = radii
                layer.border_radius = max(radii)
            elif radii:
                layer.border_radius = radii[0]
        elif radius is not None:
            layer.border_radius = self._to_float(radius)

        if layer.border_radius is None and layer.border_radii is None:
            corners = [
                p.get("cornerRadius")
                for p in (raw.get("points") or [])
                if p.get("cornerRadius")
            ]
            if corners:
                radii = [self._to_float(v) or 0.0 for v in corners]
                if len(radii) == 4 and len(set(radii)) > 1:
                    layer.border_radii = radii
                    layer.border_radius = max(radii)
                elif radii:
                    layer.border_radius = max(radii)

        # 文本：font.styles[] 每段样式，content 为文字内容
        font_raw = raw.get("font")
        if isinstance(font_raw, dict):
            styles = font_raw.get("styles") or []
            layer.text_content = (
                "".join(s.get("content") or "" for s in styles)
                or font_raw.get("content")
                or raw.get("text")
                or raw.get("name")
            )
            s0 = styles[0] if styles else {}

            # 颜色提取：优先从 s0 提取（含 value 属性），若缺失设计规范色板名称则结合 font_raw
            s0_color = self._parse_color(s0.get("color"))
            f_color = self._parse_color(font_raw.get("color"))
            color = s0_color or f_color
            if color and f_color and f_color.name and not color.name:
                color.name = f_color.name

            # 兜底：若文本颜色依然为空且图层存在填充，从 fills 提取
            if not color and raw.get("fills"):
                fills_list = raw["fills"]
                if isinstance(fills_list, list) and fills_list:
                    fill0 = fills_list[0]
                    color = self._parse_color(fill0.get("color") or fill0)

            family = (
                s0.get("font")
                or s0.get("displayName")
                or font_raw.get("font")
                or font_raw.get("displayName")
            )
            weight = self._normalize_font_weight(
                s0.get("fontWeight") or font_raw.get("fontWeight"), family or ""
            )
            size = self._to_float(s0.get("size") or font_raw.get("size"))
            line_height = self._to_float(
                s0.get("minimumLineHeight")
                or s0.get("line")
                or font_raw.get("line")
                or font_raw.get("lineHeight")
            )
            letter_spacing = self._to_float(
                s0.get("kern")
                or font_raw.get("kerning")
                or raw.get("characterSpacing")
            )

            align_raw = (
                font_raw.get("align")
                or s0.get("alignment")
                or font_raw.get("textAlignment")
            )
            text_align = _TEXT_ALIGN.get(align_raw, str(align_raw) if align_raw is not None else None)

            # 解析富文本片段
            spans: list[LanhuTextSpan] = []
            for s in styles:
                if not isinstance(s, dict):
                    continue
                content = str(s.get("content") or "")
                if not content and layer.text_content:
                    loc = s.get("location") if s.get("location") is not None else s.get("start")
                    length = s.get("length") if s.get("length") is not None else s.get("len")
                    if loc is not None and length is not None:
                        content = slice_utf16_text(layer.text_content, int(loc), int(length))
                sc = self._parse_color(s.get("color")) or color
                if sc and f_color and f_color.name and not sc.name:
                    sc.name = f_color.name
                s_family = s.get("font") or s.get("displayName") or family
                s_weight = self._normalize_font_weight(s.get("fontWeight"), s_family or "")
                spans.append(
                    LanhuTextSpan(
                        text=content,
                        size=self._to_float(s.get("size")) or size,
                        weight=s_weight,
                        family=s_family,
                        color=sc,
                        line_height=self._to_float(s.get("minimumLineHeight") or s.get("line")) or line_height,
                        letter_spacing=self._to_float(s.get("kern")) or letter_spacing,
                    )
                )

            layer.font = LanhuFont(
                size=size,
                weight=weight,
                family=family,
                line_height=line_height,
                letter_spacing=letter_spacing,
                color=color,
                color_name=color.name if color else None,
                text_align=text_align,
                spans=spans,
            )

        # 填充解析
        fills: list[LanhuFill] = []
        for f in (raw.get("fills") or []):
            if not isinstance(f, dict):
                continue
            if not f.get("isEnabled", True):
                continue
            f_type = str(f.get("type") or "color").lower()
            f_opacity = float(f.get("opacity", 1.0))
            if "gradient" in f or f_type == "gradient":
                g_obj = f.get("gradient") or f
                gradient = self._parse_gradient(g_obj, f_opacity)
                fills.append(
                    LanhuFill(
                        type="gradient",
                        gradient=gradient,
                        opacity=f_opacity,
                    )
                )
            else:
                c = self._parse_color(f.get("color") or f)
                fills.append(
                    LanhuFill(
                        type="solid",
                        color=c,
                        color_name=c.name if c else None,
                        opacity=f_opacity,
                    )
                )
        layer.fills = fills

        # 边框解析
        borders: list[LanhuBorder] = []
        for b in (raw.get("borders") or []):
            if not isinstance(b, dict):
                continue
            if not b.get("isEnabled", True):
                continue
            b_pos = _BORDER_POSITION.get(b.get("position"), str(b.get("position") or "inside"))
            c = self._parse_color(b.get("color") or b)
            borders.append(
                LanhuBorder(
                    width=float(b.get("thickness") or b.get("width") or 0),
                    color=c,
                    color_name=c.name if c else None,
                    style=b.get("style") or "solid",
                    position=b_pos,
                )
            )
        layer.borders = borders

        # 阴影解析
        shadows: list[LanhuShadow] = []
        for s in (raw.get("shadows") or []):
            if not isinstance(s, dict):
                continue
            if not s.get("isEnabled", True):
                continue
            c = self._parse_color(s.get("color") or s)
            shadows.append(
                LanhuShadow(
                    x=float(s.get("offsetX") or s.get("x") or 0),
                    y=float(s.get("offsetY") or s.get("y") or 0),
                    blur=float(s.get("blurRadius") or s.get("blur") or 0),
                    spread=float(s.get("spread") or 0),
                    color=c,
                    inner=bool(s.get("inner", False) or s.get("type") == "inner"),
                )
            )
        layer.shadows = shadows

        # 生成 CSS 属性字典
        layer.css = self._generate_layer_css(layer)

        return layer

    # ─────────────────────────── 辅助样式解析 ─────────────────────

    @classmethod
    def _parse_gradient(cls, g_raw: dict, fill_opacity: float = 1.0) -> Optional[LanhuGradient]:
        """解析渐变属性"""
        if not isinstance(g_raw, dict):
            return None
        g_type = str(g_raw.get("type") or "linear").lower()
        if "radial" in g_type:
            gradient_type = "radial"
        elif "angular" in g_type or "conic" in g_type:
            gradient_type = "angular"
        else:
            gradient_type = "linear"

        angle: Optional[float] = None
        from_pt = g_raw.get("from")
        to_pt = g_raw.get("to")
        if isinstance(from_pt, dict) and isinstance(to_pt, dict):
            try:
                fx, fy = float(from_pt.get("x", 0)), float(from_pt.get("y", 0))
                tx, ty = float(to_pt.get("x", 0)), float(to_pt.get("y", 0))
                dx = tx - fx
                dy = ty - fy
                rad = math.atan2(dy, dx)
                css_deg = (math.degrees(rad) + 90) % 360
                angle = round(css_deg, 1)
            except (ValueError, TypeError):
                pass

        raw_stops = g_raw.get("colorStops") or g_raw.get("gradientStops") or []
        stops: list[LanhuGradientStop] = []
        for s in raw_stops:
            if not isinstance(s, dict):
                continue
            pos = float(s.get("position", 0.0))
            c = cls._parse_color(s.get("color"))
            if c and fill_opacity < 1.0:
                c.a = round(c.a * fill_opacity, 3)
            stops.append(LanhuGradientStop(position=round(pos, 3), color=c))

        return LanhuGradient(type=gradient_type, angle=angle, stops=stops)

    @classmethod
    def _normalize_font_weight(cls, weight: Any, font_name: str = "") -> str:
        """标准化字重为标准数值字符串（400, 500, 600, 700 等）"""
        if weight:
            w_str = str(weight).lower().strip()
            if w_str in ("bold", "700"):
                return "700"
            if w_str in ("semibold", "semi-bold", "demibold", "600"):
                return "600"
            if w_str in ("medium", "500"):
                return "500"
            if w_str in ("regular", "normal", "400"):
                return "400"
            if w_str in ("light", "300"):
                return "300"
            if w_str in ("thin", "100"):
                return "100"
            if w_str in ("black", "heavy", "900"):
                return "900"
            if w_str.isdigit() and int(w_str) > 0:
                return w_str

        fn = font_name.lower()
        if "heavy" in fn or "black" in fn:
            return "900"
        if "extrabold" in fn or "ultrabold" in fn:
            return "800"
        if "bold" in fn or "粗体" in fn:
            return "700"
        if "semibold" in fn or "demibold" in fn or "中粗" in fn:
            return "600"
        if "medium" in fn or "中黑" in fn:
            return "500"
        if "regular" in fn or "normal" in fn or "常规" in fn:
            return "400"
        if "light" in fn or "细体" in fn:
            return "300"
        if "thin" in fn or "极细" in fn:
            return "100"
        return "400"

    @classmethod
    def _generate_layer_css(cls, layer: LanhuLayer) -> dict[str, str]:
        """根据图层属性生成开箱即用的标准 CSS 属性字典"""
        css: dict[str, str] = {}
        if layer.bounds:
            if layer.bounds.width > 0:
                w = layer.bounds.width
                css["width"] = f"{w:.1f}px".rstrip("0").rstrip(".") if w != int(w) else f"{int(w)}px"
            if layer.bounds.height > 0:
                h = layer.bounds.height
                css["height"] = f"{h:.1f}px".rstrip("0").rstrip(".") if h != int(h) else f"{int(h)}px"

        if layer.type == "text" or layer.text_content:
            if layer.font:
                f = layer.font
                if f.family:
                    css["font-family"] = f.family
                if f.size:
                    css["font-size"] = f"{int(f.size)}px" if f.size == int(f.size) else f"{f.size}px"
                if f.weight:
                    css["font-weight"] = f.weight
                if f.line_height:
                    css["line-height"] = f"{int(f.line_height)}px" if f.line_height == int(f.line_height) else f"{f.line_height}px"
                if f.letter_spacing and f.letter_spacing != 0:
                    css["letter-spacing"] = f"{f.letter_spacing}px"
                if f.text_align:
                    css["text-align"] = f.text_align
                if f.color:
                    css["color"] = f.color.to_rgba() if f.color.a < 1.0 else f.color.to_hex()
        else:
            # 形状 / 容器
            if layer.fills:
                f = layer.fills[0]
                if f.type == "gradient" and f.gradient:
                    css["background"] = f.gradient.to_css()
                elif f.color:
                    css["background"] = f.color.to_rgba() if (f.color.a < 1.0 or f.opacity < 1.0) else f.color.to_hex()

            if layer.borders:
                b = layer.borders[0]
                css["border"] = b.to_css()

            if layer.border_radii:
                css["border-radius"] = " ".join(
                    f"{int(r)}px" if r == int(r) else f"{r}px" for r in layer.border_radii
                )
            elif layer.border_radius:
                r = layer.border_radius
                css["border-radius"] = f"{int(r)}px" if r == int(r) else f"{r}px"

            if layer.shadows:
                css["box-shadow"] = ", ".join(s.to_css() for s in layer.shadows)

        if layer.opacity < 1.0:
            css["opacity"] = f"{layer.opacity:.2f}".rstrip("0").rstrip(".")

        return css

    # ─────────────────────────── 颜色解析 ────────────────────────

    @classmethod
    def _parse_color(cls, raw: Any) -> Optional[LanhuColor]:
        """解析颜色。支持包含 value、hex、rgba、r/g/b 字典或字符串"""
        if not raw:
            return None

        name = None
        if isinstance(raw, dict):
            name = raw.get("swatchName") or raw.get("name")

            # 若包含嵌套 color 对象
            if "color" in raw and isinstance(raw["color"], (dict, str)):
                nested = cls._parse_color(raw["color"])
                if nested:
                    if name and not nested.name:
                        nested.name = name
                    return nested

            # 1. 优先使用 value 字段（蓝湖 DDS 中最精准的计算后 RGBA 字符串）
            val = raw.get("value")
            if isinstance(val, str) and val.strip():
                c = cls._parse_color_str(val)
                if c:
                    c.name = name
                    return c

            # 2. 检查 hex 字段
            hex_val = raw.get("hex")
            if isinstance(hex_val, str) and hex_val.strip():
                c = cls._parse_color_str(hex_val)
                if c:
                    c.name = name
                    return c

            # 3. 检查 r, g, b
            if "r" in raw and "g" in raw and "b" in raw:
                try:
                    r = float(raw["r"])
                    g = float(raw["g"])
                    b = float(raw["b"])
                    a = float(raw.get("a", raw.get("alpha", raw.get("opacity", 1.0))))
                except (ValueError, TypeError):
                    return None

                # 判断是否为 0.0 - 1.0 比例浮点数（如 Figma 或 percentage 类型）
                is_percentage = raw.get("type") == "percentage"
                is_unit_float = (
                    r <= 1.0 and g <= 1.0 and b <= 1.0
                    and (
                        any(0.0 < v < 1.0 for v in (r, g, b))
                        or (r == 1.0 and g == 1.0 and b == 1.0 and raw.get("type") != "rgb")
                    )
                )
                if is_percentage or is_unit_float:
                    r_int = int(round(r * 255))
                    g_int = int(round(g * 255))
                    b_int = int(round(b * 255))
                else:
                    r_int = int(round(r))
                    g_int = int(round(g))
                    b_int = int(round(b))

                if a > 1.0 and a <= 100.0:
                    a = a / 100.0
                a_norm = round(max(0.0, min(1.0, a)), 3)
                return LanhuColor(r=r_int, g=g_int, b=b_int, a=a_norm, name=name)

            return None

        if isinstance(raw, str):
            c = cls._parse_color_str(raw)
            if c and name:
                c.name = name
            return c
        return None

    @classmethod
    def _parse_color_str(cls, raw: str) -> Optional[LanhuColor]:
        """解析颜色字符串（rgba / rgb / hex / transparent）"""
        raw = raw.strip()
        if not raw:
            return None
        if raw.lower() == "transparent":
            return LanhuColor(r=0, g=0, b=0, a=0.0)

        # rgba(...) 或 rgb(...)
        m = re.match(
            r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)",
            raw,
            re.IGNORECASE,
        )
        if m:
            r = int(round(float(m.group(1))))
            g = int(round(float(m.group(2))))
            b = int(round(float(m.group(3))))
            a = float(m.group(4)) if m.group(4) is not None else 1.0
            if a > 1.0 and a <= 100.0:
                a = a / 100.0
            a_norm = round(max(0.0, min(1.0, a)), 3)
            return LanhuColor(r=r, g=g, b=b, a=a_norm)

        # #RGB, #RGBA, #RRGGBB, #RRGGBBAA
        hex_str = raw.lstrip("#")
        try:
            if len(hex_str) == 3:
                r = int(hex_str[0] * 2, 16)
                g = int(hex_str[1] * 2, 16)
                b = int(hex_str[2] * 2, 16)
                return LanhuColor(r=r, g=g, b=b, a=1.0)
            elif len(hex_str) == 4:
                r = int(hex_str[0] * 2, 16)
                g = int(hex_str[1] * 2, 16)
                b = int(hex_str[2] * 2, 16)
                a = round(int(hex_str[3] * 2, 16) / 255.0, 3)
                return LanhuColor(r=r, g=g, b=b, a=a)
            elif len(hex_str) == 6:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                return LanhuColor(r=r, g=g, b=b, a=1.0)
            elif len(hex_str) == 8:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                a = round(int(hex_str[6:8], 16) / 255.0, 3)
                return LanhuColor(r=r, g=g, b=b, a=a)
        except ValueError:
            pass

        return None

    # ─────────────────────────── 切图资源 ────────────────────────

    def _parse_assets(self, nodes: list[dict]) -> list[LanhuAsset]:
        """可导出（exportable）图层即切图：svgUrl 提供 svg，imageUrl 统一提供 webp"""
        out: list[LanhuAsset] = []
        for n in nodes:
            if not n.get("exportable"):
                continue
            img = n.get("image") or {}
            name = n.get("name") or n.get("id") or "asset"
            size = img.get("size") or {}
            nid = str(n.get("id") or "")
            if img.get("svgUrl"):
                out.append(
                    LanhuAsset(
                        id=f"{nid}:svg", name=name, format="svg",
                        width=self._to_float(size.get("width")),
                        height=self._to_float(size.get("height")),
                        download_url=img["svgUrl"],
                    )
                )
            if img.get("imageUrl"):
                out.append(
                    LanhuAsset(
                        id=f"{nid}:webp", name=name, format="webp",
                        width=self._to_float(size.get("width")),
                        height=self._to_float(size.get("height")),
                        download_url=img["imageUrl"],
                    )
                )
        return out

    async def get_assets(
        self, project_id: str, image_id: str, team_id: str | None = None
    ) -> list[LanhuAsset]:
        """获取设计图中的切图列表（svg 为矢量图标，webp 为位图切图）"""
        _, dds = await self._fetch_dds(project_id, image_id, team_id)
        if "artboard" in dds:
            return self._parse_figma_assets(dds.get("artboard") or {})
        return self._parse_assets(dds.get("info") or [])

    async def resolve_invite_link(self, sid: str) -> dict:
        """解析蓝湖分享/邀请链接短码（通过官方 /api/share/url/resolve）"""
        result = await self._post("/api/share/url/resolve", json={"short_id": sid})
        return result or {}

    # ─────────────────────────── 原型 / 产品文档 (Axure) ───────────

    async def _resolve_team_id_for_project(self, project_id: str) -> Optional[str]:
        """尝试反查 project_id 所属的 team_id"""
        try:
            teams = await self.get_teams()
            if not teams:
                return None
            if len(teams) == 1:
                return teams[0].id
            for t in teams:
                try:
                    res = await self._post(
                        "/workbench/api/workbench/abstractfile/list",
                        json={"tenantId": t.id, "fid": "all"},
                    )
                    if isinstance(res, list):
                        for item in res:
                            if item.get("sourceId") == project_id:
                                return t.id
                except Exception:
                    continue
            return teams[0].id
        except Exception as e:
            logger.debug(f"反查 team_id 失败: {e}")
            return None

    async def get_product_documents(
        self, project_id: str, team_id: str | None = None
    ) -> list[LanhuProductDoc]:
        """获取项目下的产品需求/Axure 原型文档列表"""
        if not team_id:
            team_id = await self._resolve_team_id_for_project(project_id)
        params = {"project_id": project_id}
        if team_id:
            params["team_id"] = team_id
        result = await self._get("/api/project/product_documents", params=params)
        if not isinstance(result, list):
            return []

        out: list[LanhuProductDoc] = []
        for doc in result:
            if not isinstance(doc, dict):
                continue
            doc_id = str(doc.get("id") or "")
            out.append(
                LanhuProductDoc(
                    id=doc_id,
                    name=doc.get("name") or "",
                    type=doc.get("type") or "axure",
                    project_id=project_id,
                    team_id=team_id,
                    last_version_num=doc.get("last_version_num"),
                    latest_version=str(doc.get("latest_version") or ""),
                    create_time=str(doc.get("create_time") or ""),
                    update_time=str(doc.get("update_time") or ""),
                    url=f"https://lanhuapp.com/web/#/item/project/productDoc?pid={project_id}&doc_id={doc_id}",
                )
            )
        return out

    async def get_axure_sitemap(
        self, project_id: str, doc_id: str, team_id: str | None = None
    ) -> dict:
        """获取 Axure 文档的目录结构（sitemap）及页面清单"""
        if not team_id:
            team_id = await self._resolve_team_id_for_project(project_id)
        params = {"image_id": doc_id, "project_id": project_id}
        if team_id:
            params["team_id"] = team_id

        # 1. 查询文档版本及公开 OSS json_url
        result = await self._get("/api/project/image", params=params)
        if not isinstance(result, dict):
            raise LanhuAPIError(f"未找到文档 {doc_id} 的信息")

        versions = result.get("versions") or []
        if not versions:
            raise LanhuAPIError(f"文档 {doc_id} 没有可用版本")

        version_info = versions[0]
        json_url = version_info.get("json_url")
        if not json_url:
            raise LanhuAPIError(f"文档 {doc_id} 未找到 json_url 数据地址")

        # 2. 从 OSS 拉取 sitemap json
        async with self._download_http_client() as client:
            resp = await client.get(json_url)
            resp.raise_for_status()
            sitemap_data = resp.json()

        raw_sitemap = sitemap_data.get("sitemap") or sitemap_data
        pages = extract_axure_pages_from_sitemap(raw_sitemap)
        base_url = json_url.rsplit("/", 1)[0]

        return {
            "doc_id": doc_id,
            "project_id": project_id,
            "doc_name": result.get("name") or "",
            "version": version_info.get("version_num") or version_info.get("id"),
            "base_url": base_url,
            "page_count": len(pages),
            "pages": pages,
            "pages_manifest": sitemap_data.get("pages") or {},
        }

    async def get_axure_page_content(
        self, project_id: str, doc_id: str, page_name_or_url: str, team_id: str | None = None
    ) -> LanhuAxurePage:
        """读取 Axure 原型单个页面的需求文本、黄色便签 (annotations) 与备注 (notes)"""
        sitemap_info = await self.get_axure_sitemap(project_id, doc_id, team_id=team_id)
        pages = sitemap_info.get("pages") or []
        base_url = sitemap_info.get("base_url") or ""
        pages_manifest = sitemap_info.get("pages_manifest") or {}

        # 查找目标页面
        target_page_dict: Optional[dict] = None
        target_query = page_name_or_url.strip()
        for p in pages:
            if target_query in (p.get("name"), p.get("filename"), p.get("id"), p.get("path")):
                target_page_dict = p
                break
        if not target_page_dict:
            # 模糊匹配名称
            for p in pages:
                if (
                    target_query.lower() in p.get("name", "").lower()
                    or target_query.lower() in p.get("filename", "").lower()
                ):
                    target_page_dict = p
                    break

        if not target_page_dict:
            raise LanhuAPIError(f"在文档中未找到页面: {page_name_or_url}")

        filename = target_page_dict.get("filename") or ""
        page_obj = LanhuAxurePage(
            id=target_page_dict.get("id") or "",
            name=target_page_dict.get("name") or "",
            filename=filename,
            type=target_page_dict.get("type") or "Wireframe",
            level=target_page_dict.get("level") or 0,
            folder=target_page_dict.get("folder") or "根目录",
            path=target_page_dict.get("path") or "",
            has_children=target_page_dict.get("has_children", False),
        )

        manifest_entry = pages_manifest.get(filename) or {}
        html_url = None
        data_js_url = None

        if isinstance(manifest_entry, dict):
            html_info = manifest_entry.get("html") or {}
            if isinstance(html_info, dict) and html_info.get("sign_md5"):
                html_url = f"{base_url}/{html_info['sign_md5']}.html"
            data_info = manifest_entry.get("dataJs") or {}
            if isinstance(data_info, dict) and data_info.get("sign_md5"):
                data_js_url = f"{base_url}/pages/{data_info['sign_md5']}.js"

        if not html_url and base_url and filename:
            html_url = f"{base_url}/{filename}"

        async with self._download_http_client() as client:
            # 提取 HTML 文本
            if html_url:
                try:
                    resp = await client.get(html_url)
                    if resp.status_code == 200:
                        page_obj.text_content = extract_axure_page_text(resp.text)
                except Exception as e:
                    logger.warning(f"下载页面 HTML 失败 ({html_url}): {e}")

            # 提取 data.js 数据
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            candidate_js_urls = [data_js_url] if data_js_url else []
            candidate_js_urls.append(f"{base_url}/files/{stem}/data.js")

            for js_url in candidate_js_urls:
                if not js_url:
                    continue
                try:
                    resp = await client.get(js_url)
                    if resp.status_code == 200:
                        parsed_js = parse_axure_data_js(resp.text)
                        page_obj.annotations = parsed_js.get("annotations") or []
                        page_obj.notes = parsed_js.get("notes") or {}
                        break
                except Exception as e:
                    logger.debug(f"尝试下载 data.js ({js_url}) 失败: {e}")

        return page_obj

    async def inspect_url(self, url: str) -> dict:
        """智能解析任意蓝湖 URL 并返回相应项目画板/单图详情/文档信息"""
        from .url_parser import parse_lanhu_url

        parsed = parse_lanhu_url(url)
        if parsed.url_type == "invite_link" and parsed.sid:
            try:
                invite_res = await self.resolve_invite_link(parsed.sid)
                target_url = (
                    invite_res.get("url")
                    or invite_res.get("target_url")
                    or invite_res.get("redirect_url")
                )
                if target_url:
                    inner_result = await self.inspect_url(target_url)
                    inner_result["invite_sid"] = parsed.sid
                    return inner_result
                return {
                    "type": "invite_link",
                    "url": url,
                    "parsed": parsed.model_dump(),
                    "invite_data": invite_res,
                    "message": "已尝试解析邀请链接，详情见 invite_data。",
                }
            except Exception as e:
                return {
                    "type": "invite_link",
                    "url": url,
                    "parsed": parsed.model_dump(),
                    "error": f"解析邀请链接失败: {e}",
                }

        if parsed.url_type == "screen_detail" and parsed.project_id and parsed.image_id:
            screen = await self.get_annotations(
                project_id=parsed.project_id,
                image_id=parsed.image_id,
                team_id=parsed.team_id,
            )
            return {
                "type": "screen_detail",
                "url": url,
                "parsed": parsed.model_dump(),
                "screen": {
                    "id": screen.id,
                    "name": screen.name,
                    "width": screen.width,
                    "height": screen.height,
                    "is_oversized": screen.is_oversized,
                    "thumbnail_url": screen.thumbnail_url,
                    "layer_count": len(screen.layers),
                    "asset_count": len(screen.assets),
                    "assets": [
                        {
                            "id": a.id,
                            "name": a.name,
                            "format": a.format,
                            "download_url": a.download_url,
                        }
                        for a in screen.assets
                    ],
                },
                "message": f"成功识别单张设计图: {screen.name} ({screen.width}x{screen.height})。可调用 lanhu_get_annotations 获取完整图层与 CSS。",
            }

        if parsed.url_type == "stage_project" and parsed.project_id:
            screens = await self.get_screens(
                project_id=parsed.project_id,
                team_id=parsed.team_id,
            )
            return {
                "type": "stage_project",
                "url": url,
                "parsed": parsed.model_dump(),
                "screen_count": len(screens),
                "screens": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "width": s.width,
                        "height": s.height,
                        "is_oversized": s.is_oversized,
                        "thumbnail_url": s.thumbnail_url,
                    }
                    for s in screens
                ],
                "message": f"成功获取项目下的 {len(screens)} 个设计画板。可调用 lanhu_get_annotations(project_id='{parsed.project_id}', image_id=...) 查看具体画板标注。",
            }

        if parsed.url_type == "product_doc":
            sitemap_info = None
            if parsed.project_id and parsed.doc_id:
                try:
                    sitemap_info = await self.get_axure_sitemap(
                        parsed.project_id, parsed.doc_id, team_id=parsed.team_id
                    )
                except Exception as e:
                    logger.warning(f"inspect_url 获取原型 sitemap 失败: {e}")

            if sitemap_info:
                pages = sitemap_info.get("pages") or []
                return {
                    "type": "product_doc",
                    "url": url,
                    "parsed": parsed.model_dump(),
                    "doc_name": sitemap_info.get("doc_name"),
                    "page_count": len(pages),
                    "pages": [
                        {
                            "name": p.get("name"),
                            "filename": p.get("filename"),
                            "folder": p.get("folder"),
                            "path": p.get("path"),
                        }
                        for p in pages
                    ],
                    "message": (
                        f"成功识别 Axure/原型文档《{sitemap_info.get('doc_name')}》，包含 {len(pages)} 个页面。"
                        f"可调用 lanhu_get_page_content(url='...', page_name=...) 查看特定页面的需求说明与便签。"
                    ),
                }

            return {
                "type": "product_doc",
                "url": url,
                "parsed": parsed.model_dump(),
                "message": f"已识别为蓝湖 Axure/原型文档 (doc_id={parsed.doc_id}, project_id={parsed.project_id})。",
            }

        return {
            "type": "unknown",
            "url": url,
            "parsed": parsed.model_dump(),
            "message": "未能识别出具体的蓝湖项目或画板，请确认 URL 格式是否正确。",
        }

    def _download_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=60.0, follow_redirects=True, trust_env=False)

    async def download_asset(
        self, asset: LanhuAsset, save_dir: Optional[str] = None
    ) -> str:
        """下载切图资源到本地文件。所有位图切图统一转换为 WebP 格式保存，矢量图标保持 SVG 格式。具备超大图防护。"""
        if not asset.download_url:
            raise LanhuAPIError(f"资源 {asset.name} 没有下载链接")

        if not save_dir:
            save_dir = os.getenv("LANHU_DOWNLOAD_DIR", "~/Downloads/lanhu_assets")
        save_path = Path(save_dir).expanduser()
        save_path.mkdir(parents=True, exist_ok=True)

        # 清除文件名可能自带的图片后缀，避免生成类似 icon.png.webp 的文件名
        clean_name = re.sub(r"\.(png|jpe?g|webp|svg)$", "", asset.name, flags=re.IGNORECASE)
        safe_name = re.sub(r"[^\w\-]", "_", clean_name).strip("_") or "asset"

        async with self._download_http_client() as client:
            resp = await client.get(asset.download_url)  # OSS 直链，公开
            resp.raise_for_status()

            content = resp.content
            # 判断是否为 SVG 矢量图
            is_svg = (
                content.strip().startswith(b"<svg")
                or content.strip().startswith(b"<?xml")
                or b"<svg" in content[:300]
            )

            if is_svg:
                file_path = save_path / f"{safe_name}.svg"
                file_path.write_bytes(content)
            else:
                # 所有位图一律以高质量无损 WebP 格式保存，增加对超大图防解压炸弹保护
                import io
                import warnings
                from PIL import Image

                file_path = save_path / f"{safe_name}.webp"
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombError)
                    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                    try:
                        with Image.open(io.BytesIO(content)) as im:
                            if im.width * im.height > 40_000_000:
                                logger.warning(
                                    f"资源 {asset.name} 尺寸超大 ({im.width}x{im.height})，以原始格式保存"
                                )
                                orig_ext = (im.format or "png").lower()
                                file_path = save_path / f"{safe_name}.{orig_ext}"
                                file_path.write_bytes(content)
                            else:
                                im.save(file_path, format="WEBP", lossless=True)
                    except Image.DecompressionBombError:
                        logger.warning(f"资源 {asset.name} 触发解压炸弹限制，以原始字节流直接保存")
                        file_path = save_path / f"{safe_name}.bin"
                        file_path.write_bytes(content)

        logger.info(f"已下载: {file_path} ({file_path.stat().st_size} bytes)")
        return str(file_path)

    async def batch_download_assets(
        self, assets: list[LanhuAsset], save_dir: Optional[str] = None
    ) -> dict:
        """批量并发下载切图资源，并在目标目录生成 manifest.json 清单"""
        if not save_dir:
            save_dir = os.getenv("LANHU_DOWNLOAD_DIR", "~/Downloads/lanhu_assets")
        save_path = Path(save_dir).expanduser()
        save_path.mkdir(parents=True, exist_ok=True)

        import asyncio
        from datetime import datetime

        # 并发控制：最多 5 个并发下载
        sem = asyncio.Semaphore(5)

        async def _download_one(asset: LanhuAsset) -> dict:
            async with sem:
                try:
                    file_path = await self.download_asset(asset, save_dir=str(save_path))
                    p = Path(file_path)
                    clean_id = re.sub(r"[^\w]", "_", asset.name).strip("_")
                    var_name = "".join(part.capitalize() for part in clean_id.split("_") if part) or "Asset"
                    rel_path = f"./{p.name}"
                    return {
                        "id": asset.id,
                        "name": asset.name,
                        "format": p.suffix.lstrip("."),
                        "file_path": str(p),
                        "file_name": p.name,
                        "relative_path": rel_path,
                        "size_bytes": p.stat().st_size if p.exists() else 0,
                        "width": asset.width,
                        "height": asset.height,
                        "import_statement": f"import {var_name} from '{rel_path}';",
                        "status": "success",
                    }
                except Exception as e:
                    logger.warning(f"下载切图 {asset.name} 失败: {e}")
                    return {
                        "id": asset.id,
                        "name": asset.name,
                        "status": "failed",
                        "error": str(e),
                    }

        tasks = [_download_one(a) for a in assets]
        results = await asyncio.gather(*tasks) if tasks else []

        manifest = {
            "export_time": datetime.now().isoformat(),
            "total_count": len(assets),
            "success_count": sum(1 for r in results if r.get("status") == "success"),
            "save_dir": str(save_path),
            "assets": results,
        }

        # 写入 manifest.json
        manifest_file = save_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return manifest

    async def get_design_tokens(
        self, project_id: str, image_id: Optional[str] = None, team_id: Optional[str] = None
    ) -> LanhuDesignTokens:
        """从单个画板或项目代表性画板中聚合提取 Design Tokens"""
        from .tokens import extract_design_tokens

        if image_id:
            screen = await self.get_annotations(project_id, image_id, team_id=team_id)
            return extract_design_tokens(screen)

        screens = await self.get_screens(project_id, team_id=team_id)
        # 为避免单次请求过多，取前 10 张代表性画板分析标注
        target_screens = screens[:10]
        full_screens: list[LanhuScreen] = []
        for s in target_screens:
            try:
                full_s = await self.get_annotations(project_id, s.id, team_id=team_id)
                full_screens.append(full_s)
            except Exception as e:
                logger.warning(f"获取画板 {s.id} 标注失败: {e}")

        return extract_design_tokens(full_screens if full_screens else screens)

    async def get_layout_skeleton(
        self, project_id: str, image_id: str, team_id: Optional[str] = None
    ) -> LanhuLayoutNode:
        """推断单个画板的智能 Flexbox 响应式布局骨架树"""
        from .layout import infer_screen_skeleton

        screen = await self.get_annotations(project_id, image_id, team_id=team_id)
        return infer_screen_skeleton(screen)


# 边框位置中英映射
_BORDER_POSITION = {
    "内边框": "inside",
    "外边框": "outside",
    "中心边框": "center",
    "居中边框": "center",
    "居中": "center",
    "inside": "inside",
    "outside": "outside",
    "center": "center",
    "INSIDE": "inside",
    "OUTSIDE": "outside",
    "CENTER": "center",
    0: "center",
    1: "inside",
    2: "outside",
}

# 对齐方式映射
_TEXT_ALIGN = {
    0: "left",
    1: "right",
    2: "center",
    3: "justify",
    "left": "left",
    "center": "center",
    "right": "right",
    "justify": "justify",
    "LEFT": "left",
    "CENTER": "center",
    "RIGHT": "right",
    "JUSTIFIED": "justify",
}

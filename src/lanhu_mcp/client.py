"""蓝湖 API 客户端 — 封装所有 HTTP 请求，解析返回数据

API 契约（2026-08 逆向自 lanhuapp.com webapp）：
- 认证：Cookie `session=...; user_token=...`（session 必需）
- 响应包络：`code` 为 "00000"/0 表示成功，数据在 `result` 或 `data` 字段
- 图层标注数据：image 元信息中最新版本的 `json_url` 指向公开 OSS JSON
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from .auth import LanhuAuth, LanhuAuthError
from .models import (
    LanhuAsset,
    LanhuBorder,
    LanhuBounds,
    LanhuColor,
    LanhuFill,
    LanhuFont,
    LanhuLayer,
    LanhuProject,
    LanhuScreen,
    LanhuShadow,
    LanhuTeam,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://lanhuapp.com"


class LanhuAPIError(Exception):
    """API 调用错误"""

    def __init__(self, msg: str, code: int = -1, raw: Any = None):
        super().__init__(msg)
        self.code = code
        self.raw = raw


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

    async def get_screens(self, project_id: str, team_id: str) -> list[LanhuScreen]:
        """获取项目下所有设计图（画板）列表"""
        result = await self._get(
            "/api/project/images",
            params={"project_id": project_id, "team_id": team_id},
        )
        images = (result or {}).get("images", []) if isinstance(result, dict) else []
        return [self._parse_screen_basic(img, project_id) for img in images]

    async def search_images(
        self, project_id: str, team_id: str, keyword: str
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

    async def _fetch_dds(self, project_id: str, image_id: str, team_id: str) -> tuple[LanhuScreen, dict]:
        """取设计图元信息 + 最新版本的图层 JSON（DDS）"""
        info = await self._get(
            "/api/project/image",
            params={
                "image_id": image_id,
                "project_id": project_id,
                "team_id": team_id,
                "dds_status": 1,
            },
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

    async def get_annotations(self, project_id: str, image_id: str, team_id: str) -> LanhuScreen:
        """获取单张设计图的完整标注：图层树 + 切图资源"""
        screen, dds = await self._fetch_dds(project_id, image_id, team_id)
        nodes = dds.get("info") or []
        screen.layers = self._build_layers(nodes)
        screen.assets = self._parse_assets(nodes)
        return screen

    # ─────────────────────────── 图层解析 ────────────────────────

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
        radius = raw.get("radius")
        if isinstance(radius, list):
            layer.border_radius = max(radius) if radius else None
        elif radius is not None:
            layer.border_radius = self._to_float(radius)
        if layer.border_radius is None:
            corners = [
                p.get("cornerRadius") for p in (raw.get("points") or [])
                if p.get("cornerRadius")
            ]
            layer.border_radius = max(corners) if corners else None

        # 文本：font.styles[] 每段样式，content 为文字内容
        font_raw = raw.get("font")
        if isinstance(font_raw, dict):
            styles = font_raw.get("styles") or []
            layer.text_content = "".join(s.get("content") or "" for s in styles)
            s0 = styles[0] if styles else {}
            layer.font = LanhuFont(
                size=self._to_float(s0.get("size") or font_raw.get("size")),
                weight=str(s0.get("fontWeight") or ""),
                family=s0.get("font") or s0.get("displayName"),
                line_height=self._to_float(
                    s0.get("minimumLineHeight") or font_raw.get("line")
                ),
                letter_spacing=self._to_float(s0.get("kern") or font_raw.get("kerning")),
                color=self._parse_color(s0.get("color") or font_raw.get("color")),
                text_align=font_raw.get("align"),
            )

        # 填充
        layer.fills = [
            LanhuFill(
                type=str(f.get("type") or "color"),
                color=self._parse_color(f.get("color")),
                opacity=float(f.get("opacity", 1.0)),
            )
            for f in (raw.get("fills") or [])
        ]

        # 边框
        layer.borders = [
            LanhuBorder(
                width=float(b.get("thickness") or 0),
                color=self._parse_color(b.get("color")),
                style="solid",
                position=_BORDER_POSITION.get(b.get("position"), str(b.get("position") or "inside")),
            )
            for b in (raw.get("borders") or [])
            if b.get("isEnabled", True)
        ]

        # 阴影
        layer.shadows = [
            LanhuShadow(
                x=float(s.get("offsetX") or 0),
                y=float(s.get("offsetY") or 0),
                blur=float(s.get("blurRadius") or 0),
                spread=float(s.get("spread") or 0),
                color=self._parse_color(s.get("color")),
            )
            for s in (raw.get("shadows") or [])
        ]

        return layer

    # ─────────────────────────── 颜色解析 ────────────────────────

    @classmethod
    def _parse_color(cls, raw: Any) -> Optional[LanhuColor]:
        """解析颜色。新格式为 {value: "rgba(r,g,b,a)"}；兼容 #RRGGBB 字符串"""
        if isinstance(raw, dict):
            raw = raw.get("value") or raw.get("hex")
        if not isinstance(raw, str):
            return None
        raw = raw.strip()

        m = re.match(r"rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\)", raw)
        if m:
            return LanhuColor(
                r=int(m.group(1)), g=int(m.group(2)), b=int(m.group(3)),
                a=float(m.group(4)) if m.group(4) is not None else 1.0,
            )

        hex_str = raw.lstrip("#")
        if len(hex_str) in (6, 8):
            try:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                a = int(hex_str[6:8], 16) / 255 if len(hex_str) == 8 else 1.0
                return LanhuColor(r=r, g=g, b=b, a=a)
            except ValueError:
                pass
        return None

    # ─────────────────────────── 切图资源 ────────────────────────

    def _parse_assets(self, nodes: list[dict]) -> list[LanhuAsset]:
        """可导出（exportable）图层即切图，image 里有 svg/png 直链，位图默认提供 webp"""
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
                # 位图默认推荐 webp，同时也保留 png 选项
                out.append(
                    LanhuAsset(
                        id=f"{nid}:webp", name=name, format="webp",
                        width=self._to_float(size.get("width")),
                        height=self._to_float(size.get("height")),
                        download_url=img["imageUrl"],
                    )
                )
                out.append(
                    LanhuAsset(
                        id=f"{nid}:png", name=name, format="png",
                        width=self._to_float(size.get("width")),
                        height=self._to_float(size.get("height")),
                        download_url=img["imageUrl"],
                    )
                )
        return out

    async def get_assets(self, project_id: str, image_id: str, team_id: str) -> list[LanhuAsset]:
        """获取设计图中的切图列表（svg/webp/png 直链，无需认证即可下载）"""
        _, dds = await self._fetch_dds(project_id, image_id, team_id)
        return self._parse_assets(dds.get("info") or [])

    async def download_asset(
        self, asset: LanhuAsset, save_dir: Optional[str] = None
    ) -> str:
        """下载切图资源到本地文件，若格式为 webp 则自动将位图转换为 WebP 格式，返回保存路径"""
        if not asset.download_url:
            raise LanhuAPIError(f"资源 {asset.name} 没有下载链接")

        if not save_dir:
            save_dir = os.getenv("LANHU_DOWNLOAD_DIR", "~/Downloads/lanhu_assets")
        save_path = Path(save_dir).expanduser()
        save_path.mkdir(parents=True, exist_ok=True)

        ext = (asset.format or "webp").lower()
        safe_name = re.sub(r"[^\w\-.]", "_", asset.name)
        file_path = save_path / f"{safe_name}.{ext}"

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, trust_env=False) as client:
            resp = await client.get(asset.download_url)  # OSS 直链，公开
            resp.raise_for_status()

            if ext == "webp":
                # 如果是 SVG 文本内容则不转为 webp，保持 svg
                if resp.content.strip().startswith(b"<svg") or resp.content.strip().startswith(b"<?xml"):
                    file_path = save_path / f"{safe_name}.svg"
                    file_path.write_bytes(resp.content)
                else:
                    import io
                    from PIL import Image
                    with Image.open(io.BytesIO(resp.content)) as im:
                        im.save(file_path, format="WEBP", lossless=True)
            else:
                file_path.write_bytes(resp.content)

        logger.info(f"已下载: {file_path} ({file_path.stat().st_size} bytes)")
        return str(file_path)


# 边框位置中文 → 英文
_BORDER_POSITION = {"内边框": "inside", "外边框": "outside", "center": "center"}

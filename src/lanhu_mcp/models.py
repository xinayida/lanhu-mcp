"""蓝湖数据模型定义"""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ─────────────────────────── 通用 ────────────────────────────

class LanhuColor(BaseModel):
    """颜色模型，支持 HEX、RGBA 与设计规范色板名称"""
    r: int = 0
    g: int = 0
    b: int = 0
    a: float = 1.0
    name: Optional[str] = None  # 色板/token 名称，如 "文字&图标色/Wh2-Font2 60%"

    def to_hex(self, include_alpha: bool = False) -> str:
        """返回十六进制颜色。如果 include_alpha 为 True 且 a < 1.0，则返回 #RRGGBBAA"""
        if include_alpha and self.a < 1.0:
            alpha_int = int(round(self.a * 255))
            return f"#{self.r:02X}{self.g:02X}{self.b:02X}{alpha_int:02X}"
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

    def to_rgba(self) -> str:
        """返回标准 rgba 格式，透明度去除末尾多余零"""
        a_str = f"{self.a:.2f}".rstrip("0").rstrip(".") if self.a != int(self.a) else str(int(self.a))
        return f"rgba({self.r},{self.g},{self.b},{a_str})"


class LanhuBounds(BaseModel):
    """图层位置与尺寸"""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


# ─────────────────────────── 团队 & 项目 ─────────────────────

class LanhuTeam(BaseModel):
    """团队"""
    id: str
    name: str
    role: Optional[str] = None
    member_count: Optional[int] = None


class LanhuProject(BaseModel):
    """项目"""
    id: str
    name: str
    description: Optional[str] = None
    cover_url: Optional[str] = None
    team_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─────────────────────────── 样式属性 ────────────────────────

class LanhuGradientStop(BaseModel):
    """渐变色标"""
    position: float = 0.0
    color: Optional[LanhuColor] = None


class LanhuGradient(BaseModel):
    """渐变信息"""
    type: str = "linear"  # linear / radial / angular
    angle: Optional[float] = None  # 渐变角度（度数，如 180）
    stops: list[LanhuGradientStop] = Field(default_factory=list)

    def to_css(self) -> str:
        """生成 CSS gradient 字符串"""
        stops_str = ", ".join(
            f"{s.color.to_rgba() if s.color else 'transparent'} {int(round(s.position * 100))}%"
            for s in self.stops
        )
        if self.type == "linear":
            angle_str = f"{int(round(self.angle))}deg, " if self.angle is not None else ""
            return f"linear-gradient({angle_str}{stops_str})"
        elif self.type == "radial":
            return f"radial-gradient(circle, {stops_str})"
        return f"linear-gradient({stops_str})"


class LanhuTextSpan(BaseModel):
    """富文本片段（多样式文字）"""
    text: str = ""
    size: Optional[float] = None
    weight: Optional[str] = None
    family: Optional[str] = None
    line_height: Optional[float] = None
    letter_spacing: Optional[float] = None
    color: Optional[LanhuColor] = None


class LanhuFont(BaseModel):
    """字体信息"""
    size: Optional[float] = None
    weight: Optional[str] = None
    family: Optional[str] = None
    line_height: Optional[float] = None
    letter_spacing: Optional[float] = None
    color: Optional[LanhuColor] = None
    color_name: Optional[str] = None
    text_align: Optional[str] = None
    spans: list[LanhuTextSpan] = Field(default_factory=list)


class LanhuFill(BaseModel):
    """填充"""
    type: str = "solid"  # solid / gradient / image
    color: Optional[LanhuColor] = None
    color_name: Optional[str] = None
    gradient: Optional[LanhuGradient] = None
    opacity: float = 1.0


class LanhuShadow(BaseModel):
    """阴影"""
    x: float = 0
    y: float = 0
    blur: float = 0
    spread: float = 0
    color: Optional[LanhuColor] = None
    inner: bool = False

    def to_css(self) -> str:
        """生成 CSS box-shadow 字符串"""
        c = self.color.to_rgba() if self.color else "rgba(0,0,0,0.2)"
        inset = "inset " if self.inner else ""
        return f"{inset}{self.x}px {self.y}px {self.blur}px {self.spread}px {c}"


class LanhuBorder(BaseModel):
    """边框"""
    width: float = 0
    color: Optional[LanhuColor] = None
    color_name: Optional[str] = None
    style: str = "solid"
    position: str = "inside"  # inside / outside / center

    def to_css(self) -> str:
        """生成 CSS border 字符串"""
        c = self.color.to_rgba() if self.color else "transparent"
        return f"{self.width}px {self.style} {c}"


class LanhuLayer(BaseModel):
    """图层（设计图标注的基本单元）"""
    id: str
    name: str
    type: str  # text / rect / group / image / vector 等
    bounds: Optional[LanhuBounds] = None
    opacity: float = 1.0
    visible: bool = True
    # 文本
    text_content: Optional[str] = None
    font: Optional[LanhuFont] = None
    # 视觉属性
    fills: list[LanhuFill] = Field(default_factory=list)
    borders: list[LanhuBorder] = Field(default_factory=list)
    shadows: list[LanhuShadow] = Field(default_factory=list)
    border_radius: Optional[float] = None
    border_radii: Optional[list[float]] = None  # 四角单独圆角 [top_left, top_right, bottom_right, bottom_left]
    # CSS 样式字典
    css: Optional[dict[str, str]] = None
    # 子图层
    children: list["LanhuLayer"] = Field(default_factory=list)
    # 原始数据（调试用）
    raw: Optional[dict[str, Any]] = Field(default=None, exclude=True)


LanhuLayer.model_rebuild()


# ─────────────────────────── 切图 / 资源 ─────────────────────

class LanhuAsset(BaseModel):
    """切图 / 图标资源"""
    id: str
    name: str
    format: str = "png"  # png / jpg / svg / webp
    scale: str = "1x"
    width: Optional[float] = None
    height: Optional[float] = None
    download_url: Optional[str] = None


# ─────────────────────────── 设计图（Screen）────────────────

class LanhuScreen(BaseModel):
    """单张设计图（一个页面/画板）"""
    id: str
    name: str
    width: Optional[float] = None
    height: Optional[float] = None
    thumbnail_url: Optional[str] = None
    project_id: Optional[str] = None
    # 详情字段（调用 get_annotations 后填充）
    layers: list[LanhuLayer] = Field(default_factory=list)
    assets: list[LanhuAsset] = Field(default_factory=list)
    background_color: Optional[LanhuColor] = None


# ─────────────────────────── 用户 ────────────────────────────

class LanhuUser(BaseModel):
    """登录用户信息"""
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None

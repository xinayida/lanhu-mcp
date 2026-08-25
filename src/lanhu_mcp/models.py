"""蓝湖数据模型定义"""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ─────────────────────────── 通用 ────────────────────────────

class LanhuColor(BaseModel):
    """颜色"""
    r: int = 0
    g: int = 0
    b: int = 0
    a: float = 1.0

    def to_hex(self) -> str:
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

    def to_rgba(self) -> str:
        return f"rgba({self.r},{self.g},{self.b},{self.a})"


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


# ─────────────────────────── 设计图 ──────────────────────────

class LanhuFont(BaseModel):
    """字体信息"""
    size: Optional[float] = None
    weight: Optional[str] = None
    family: Optional[str] = None
    line_height: Optional[float] = None
    letter_spacing: Optional[float] = None
    color: Optional[LanhuColor] = None
    text_align: Optional[str] = None


class LanhuFill(BaseModel):
    """填充"""
    type: str = "solid"  # solid / gradient / image
    color: Optional[LanhuColor] = None
    opacity: float = 1.0


class LanhuShadow(BaseModel):
    """阴影"""
    x: float = 0
    y: float = 0
    blur: float = 0
    spread: float = 0
    color: Optional[LanhuColor] = None


class LanhuBorder(BaseModel):
    """边框"""
    width: float = 0
    color: Optional[LanhuColor] = None
    style: str = "solid"
    position: str = "inside"  # inside / outside / center


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

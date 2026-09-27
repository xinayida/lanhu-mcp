"""设计规范 Token 提取器 — 从蓝湖设计图层中聚合提取全局设计系统 Token

支持提取：
- 颜色色板与 Token (Colors)
- 字体排版系统 (Typography: Font Families, Sizes, Weights, Line Heights)
- 边界圆角规格 (Radii)
- 投影阴影规格 (Shadows)
可一键导出为 CSS 变量、Tailwind 配置与 W3C DTCG 标准规范 JSON。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from .models import (
    LanhuColor,
    LanhuColorToken,
    LanhuDesignTokens,
    LanhuLayer,
    LanhuScreen,
)


def _slugify_token_name(name: str) -> str:
    """将色板名转为合法的 CSS 变量 / Token 名称（如 '文字&图标/Font-Main 60%' -> 'font-main-60'）"""
    # 移除百分号等非字母数字符号
    parts = re.split(r"[/\\_\-\s&]+", name)
    clean_parts = [re.sub(r"[^\w]", "", p).lower() for p in parts if p.strip()]
    slug = "-".join(clean_parts).strip("-")
    if not slug:
        return "color"
    if not slug.startswith("color"):
        return f"color-{slug}"
    return slug


def extract_design_tokens(screens: LanhuScreen | Iterable[LanhuScreen]) -> LanhuDesignTokens:
    """从单个或多个画板中聚合提取 Design Tokens"""
    if isinstance(screens, LanhuScreen):
        screen_list = [screens]
    else:
        screen_list = list(screens)

    color_counter: Counter[str] = Counter()
    color_names: dict[str, str] = {}
    color_rgba: dict[str, str] = {}

    font_families: set[str] = set()
    font_sizes: set[float] = set()
    font_weights: set[str] = set()
    line_heights: set[float] = set()
    radii: set[float] = set()
    shadows: set[str] = set()

    def record_color(color: LanhuColor | None, name_hint: str | None = None) -> None:
        if not color:
            return
        hex_val = color.to_hex(include_alpha=True)
        color_counter[hex_val] += 1
        if not color_rgba.get(hex_val):
            color_rgba[hex_val] = color.to_rgba()
        c_name = color.name or name_hint
        if c_name and hex_val not in color_names:
            color_names[hex_val] = c_name

    def visit_layer(layer: LanhuLayer) -> None:
        if not layer.visible:
            return

        # 1. 收集填充颜色
        for f in layer.fills:
            if f.type == "solid" and f.color:
                record_color(f.color, f.color_name)

        # 2. 收集边框颜色
        for b in layer.borders:
            if b.color:
                record_color(b.color, b.color_name)

        # 3. 收集阴影
        for s in layer.shadows:
            if s.color:
                record_color(s.color)
            shadow_css = s.to_css()
            if shadow_css:
                shadows.add(shadow_css)

        # 4. 收集圆角
        if layer.border_radius and layer.border_radius > 0:
            radii.add(round(layer.border_radius, 1))
        if layer.border_radii:
            for r in layer.border_radii:
                if r > 0:
                    radii.add(round(r, 1))

        # 5. 收集字体排版
        if layer.font:
            record_color(layer.font.color, layer.font.color_name)
            if layer.font.family:
                font_families.add(layer.font.family)
            if layer.font.size and layer.font.size > 0:
                font_sizes.add(round(layer.font.size, 1))
            if layer.font.weight:
                font_weights.add(layer.font.weight)
            if layer.font.line_height and layer.font.line_height > 0:
                line_heights.add(round(layer.font.line_height, 1))

            for sp in layer.font.spans:
                record_color(sp.color)
                if sp.family:
                    font_families.add(sp.family)
                if sp.size and sp.size > 0:
                    font_sizes.add(round(sp.size, 1))
                if sp.weight:
                    font_weights.add(sp.weight)
                if sp.line_height and sp.line_height > 0:
                    line_heights.add(round(sp.line_height, 1))

        # 递归子图层
        for child in layer.children:
            visit_layer(child)

    # 遍历所有画板的所有根图层
    for scr in screen_list:
        if scr.background_color:
            record_color(scr.background_color, "Background")
        for lyr in scr.layers:
            visit_layer(lyr)

    # 生成有序颜色 Token
    sorted_colors = color_counter.most_common()
    color_tokens: list[LanhuColorToken] = []

    used_token_names: set[str] = set()

    for idx, (hex_val, count) in enumerate(sorted_colors):
        raw_name = color_names.get(hex_val)
        if raw_name:
            base_token = _slugify_token_name(raw_name)
        else:
            # 常见黑白色判断
            if hex_val.upper() in ("#FFFFFF", "#FFFFFFFF"):
                base_token = "color-white"
            elif hex_val.upper() in ("#000000", "#000000FF"):
                base_token = "color-black"
            elif idx == 0:
                base_token = "color-primary"
            elif idx == 1:
                base_token = "color-secondary"
            else:
                base_token = f"color-{idx+1}"

        token_name = base_token
        counter = 2
        while token_name in used_token_names:
            token_name = f"{base_token}-{counter}"
            counter += 1

        used_token_names.add(token_name)

        color_tokens.append(
            LanhuColorToken(
                token_name=token_name,
                hex=hex_val,
                rgba=color_rgba.get(hex_val, hex_val),
                count=count,
                raw_name=raw_name,
            )
        )

    # 排序字号（升序）
    sorted_font_sizes = sorted(font_sizes)
    # 排序字重
    weight_order = {"300": 300, "400": 400, "500": 500, "600": 600, "700": 700, "800": 800, "900": 900}
    sorted_font_weights = sorted(
        font_weights,
        key=lambda w: weight_order.get(w, int(w) if w.isdigit() else 400),
    )
    sorted_radii = sorted(radii)
    sorted_line_heights = sorted(line_heights)

    return LanhuDesignTokens(
        colors=color_tokens,
        font_families=sorted(font_families),
        font_sizes=sorted_font_sizes,
        font_weights=sorted_font_weights,
        line_heights=sorted_line_heights,
        radii=sorted_radii,
        shadows=sorted(shadows),
    )

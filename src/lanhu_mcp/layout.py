"""布局骨架推断器 — 将蓝湖绝对定位图层树智能转换为标准 Flexbox 流式布局骨架

核心能力：
1. 语义化标签自动推断（h1-h6, p, button, img, input, div）
2. 兄弟图层流向判定（flex-row vs flex-col vs absolute/relative 堆叠）
3. 容器内外边距与间隙计算（Gap & Padding）
4. 冗余嵌套容器自动折叠清洗（消除无样式的嵌套 div）
5. 自动生成现代前端 Tailwind CSS 类名
"""

from __future__ import annotations

import math
from typing import Optional

from .models import LanhuBounds, LanhuLayer, LanhuLayoutNode


def _to_tw_gap(gap: float) -> str:
    """像素间距映射到 Tailwind gap 类名（基于 4px 基准网格）"""
    val = round(gap / 4.0)
    if val <= 0:
        return ""
    if val in (1, 2, 3, 4, 5, 6, 8, 10, 12, 16):
        return f"gap-{val}"
    return f"gap-[{int(round(gap))}px]"


def _to_tw_padding(pt: float, pr: float, pb: float, pl: float) -> list[str]:
    """内边距映射到 Tailwind padding 类名"""
    classes: list[str] = []
    # 判断四周相等
    if abs(pt - pr) <= 2 and abs(pr - pb) <= 2 and abs(pb - pl) <= 2 and pt > 2:
        val = round(pt / 4.0)
        classes.append(f"p-{val}" if val in (1, 2, 3, 4, 6, 8) else f"p-[{int(round(pt))}px]")
        return classes

    # 判断水平/垂直对称
    if abs(pt - pb) <= 2 and pt > 2:
        val_y = round(pt / 4.0)
        classes.append(f"py-{val_y}" if val_y in (1, 2, 3, 4, 6, 8) else f"py-[{int(round(pt))}px]")
    elif pt > 2:
        classes.append(f"pt-[{int(round(pt))}px]")
    if abs(pr - pl) <= 2 and pr > 2:
        val_x = round(pr / 4.0)
        classes.append(f"px-{val_x}" if val_x in (1, 2, 3, 4, 6, 8) else f"px-[{int(round(pr))}px]")
    elif pl > 2:
        classes.append(f"pl-[{int(round(pl))}px]")
    return classes


def _infer_tag(layer: LanhuLayer) -> str:
    """根据图层类型、文本与命名推断语义化 HTML 标签"""
    name_lower = layer.name.lower()

    if layer.type == "text" or layer.text_content:
        size = layer.font.size if layer.font and layer.font.size else 14.0
        if size >= 28:
            return "h1"
        elif size >= 24:
            return "h2"
        elif size >= 20:
            return "h3"
        elif size >= 16 and (layer.font and layer.font.weight in ("600", "700", "bold")):
            return "h4"
        return "p"

    # 按钮判断
    if any(k in name_lower for k in ("button", "btn", "按钮", "提交", "确定", "登录", "注册")):
        return "button"

    # 输入框判断
    if any(k in name_lower for k in ("input", "输入框", "searchbar", "搜索框", "textfield")):
        return "input"

    # 图像/切图判断
    if any(k in name_lower for k in ("image", "img", "avatar", "头像", "banner", "pic", "icon", "图标")):
        return "img"

    # 头部 / 导航
    if any(k in name_lower for k in ("header", "navbar", "导航栏", "顶部栏", "topbar")):
        return "header"
    # 底部 / Tabbar
    if any(k in name_lower for k in ("footer", "tabbar", "底部栏", "bottombar")):
        return "footer"

    return "div"


def infer_layer_layout(layer: LanhuLayer, parent_bounds: LanhuBounds | None = None) -> LanhuLayoutNode:
    """将单个图层节点及其子图层递归推断为 Flexbox 布局节点"""
    tag = _infer_tag(layer)
    b = layer.bounds or LanhuBounds()
    classes: list[str] = []

    # 基础视觉样式推断 Tailwind 类
    if layer.fills:
        for f in layer.fills:
            if f.type == "solid" and f.color:
                hex_c = f.color.to_hex()
                if hex_c.upper() in ("#FFFFFF", "#FFFFFFFF"):
                    classes.append("bg-white")
                elif hex_c.upper() in ("#000000", "#000000FF"):
                    classes.append("bg-black")
                else:
                    classes.append(f"bg-[{hex_c}]")
    if layer.border_radius and layer.border_radius > 0:
        r = layer.border_radius
        if r >= 999:
            classes.append("rounded-full")
        elif r >= 16:
            classes.append("rounded-2xl")
        elif r >= 12:
            classes.append("rounded-xl")
        elif r >= 8:
            classes.append("rounded-lg")
        elif r >= 4:
            classes.append("rounded-md")
        else:
            classes.append(f"rounded-[{int(r)}px]")

    if layer.shadows:
        classes.append("shadow-sm")

    # 过滤可见子图层
    visible_children = [c for c in layer.children if c.visible]

    # 无子节点的叶子图层（如文本或图片或空图形）
    if not visible_children:
        if layer.text_content:
            if layer.font and layer.font.color:
                c_hex = layer.font.color.to_hex()
                if c_hex.upper() in ("#FFFFFF", "#FFFFFFFF"):
                    classes.append("text-white")
                elif c_hex.upper() not in ("#000000", "#000000FF"):
                    classes.append(f"text-[{c_hex}]")
        return LanhuLayoutNode(
            id=layer.id,
            name=layer.name,
            tag=tag,
            display="block",
            bounds=layer.bounds,
            classes=classes,
            text=layer.text_content,
        )

    # 有单个子节点的简单包装器
    if len(visible_children) == 1:
        child_node = infer_layer_layout(visible_children[0], layer.bounds)
        # 如果父容器没有任何视觉样式且不是特定语义标签，则可以作为基础容器或由子元素继承
        classes.insert(0, "flex flex-col")
        return LanhuLayoutNode(
            id=layer.id,
            name=layer.name,
            tag=tag,
            display="flex",
            direction="column",
            bounds=layer.bounds,
            classes=classes,
            children=[child_node],
        )

    # 拥有多个子图层：分析相对几何位置以推断排列方向与间隙
    # 按照实际几何坐标排序
    child_bounds_list = [c.bounds or LanhuBounds() for c in visible_children]

    # 判断水平分布重叠度与垂直分布重叠度
    # 计算相邻元素的 Y 轴重叠与 X 轴重叠
    # 策略：按 Y 排序与按 X 排序
    sorted_by_y = sorted(visible_children, key=lambda c: (c.bounds.y if c.bounds else 0))
    sorted_by_x = sorted(visible_children, key=lambda c: (c.bounds.x if c.bounds else 0))

    # 计算垂直单调性与重叠
    y_gaps: list[float] = []
    y_overlaps = 0
    for i in range(len(sorted_by_y) - 1):
        c1 = sorted_by_y[i].bounds or LanhuBounds()
        c2 = sorted_by_y[i + 1].bounds or LanhuBounds()
        c1_bottom = c1.y + c1.height
        gap = c2.y - c1_bottom
        if gap < -5.0:  # 存在超过 5px 的明显重叠
            y_overlaps += 1
        y_gaps.append(max(0.0, gap))

    # 计算水平单调性与重叠
    x_gaps: list[float] = []
    x_overlaps = 0
    for i in range(len(sorted_by_x) - 1):
        c1 = sorted_by_x[i].bounds or LanhuBounds()
        c2 = sorted_by_x[i + 1].bounds or LanhuBounds()
        c1_right = c1.x + c1.width
        gap = c2.x - c1_right
        if gap < -5.0:
            x_overlaps += 1
        x_gaps.append(max(0.0, gap))

    direction = "column"
    ordered_children = sorted_by_y
    chosen_gaps = y_gaps

    if x_overlaps < y_overlaps:
        # 水平排列
        direction = "row"
        ordered_children = sorted_by_x
        chosen_gaps = x_gaps
    elif x_overlaps == y_overlaps:
        # 重叠度相同时，看跨度更大的方向
        total_y_span = max(c.bounds.y + c.bounds.height for c in visible_children if c.bounds) - min(
            c.bounds.y for c in visible_children if c.bounds
        )
        total_x_span = max(c.bounds.x + c.bounds.width for c in visible_children if c.bounds) - min(
            c.bounds.x for c in visible_children if c.bounds
        )
        if total_x_span > total_y_span * 1.5:
            direction = "row"
            ordered_children = sorted_by_x
            chosen_gaps = x_gaps
        else:
            direction = "column"
            ordered_children = sorted_by_y
            chosen_gaps = y_gaps

    # 计算平均间隙
    valid_gaps = [g for g in chosen_gaps if g > 0]
    avg_gap = (sum(valid_gaps) / len(valid_gaps)) if valid_gaps else 0.0

    # 计算内边距（子元素相对于父容器内边缘）
    padding_dict: dict[str, float] = {}
    if b.width > 0 and b.height > 0 and ordered_children:
        min_x = min((c.bounds.x if c.bounds else 0) for c in ordered_children)
        min_y = min((c.bounds.y if c.bounds else 0) for c in ordered_children)
        max_r = max(((c.bounds.x + c.bounds.width) if c.bounds else 0) for c in ordered_children)
        max_b = max(((c.bounds.y + c.bounds.height) if c.bounds else 0) for c in ordered_children)

        pt = max(0.0, min_y - b.y)
        pl = max(0.0, min_x - b.x)
        pr = max(0.0, (b.x + b.width) - max_r)
        pb = max(0.0, (b.y + b.height) - max_b)

        # 仅当 padding 在合理范围（小于半宽半高）时记录
        if pt < b.height * 0.5 and pb < b.height * 0.5 and pl < b.width * 0.5 and pr < b.width * 0.5:
            padding_dict = {
                "top": round(pt, 1),
                "right": round(pr, 1),
                "bottom": round(pb, 1),
                "left": round(pl, 1),
            }
            classes.extend(_to_tw_padding(pt, pr, pb, pl))

    # 添加 Flex 布局类
    classes.insert(0, f"flex flex-{direction}")
    if avg_gap >= 2.0:
        gap_cls = _to_tw_gap(avg_gap)
        if gap_cls:
            classes.append(gap_cls)

    # 递归生成所有子节点
    child_nodes = [infer_layer_layout(c, layer.bounds) for c in ordered_children]

    return LanhuLayoutNode(
        id=layer.id,
        name=layer.name,
        tag=tag,
        display="flex",
        direction=direction,
        gap=round(avg_gap, 1) if avg_gap > 0 else None,
        padding=padding_dict if padding_dict else None,
        bounds=layer.bounds,
        classes=classes,
        children=child_nodes,
    )


def infer_screen_skeleton(screen: LanhuScreen) -> LanhuLayoutNode:
    """推断整个设计图（画板）的根骨架树"""
    root_layer = LanhuLayer(
        id=f"screen-{screen.id}",
        name=screen.name,
        type="artboard",
        bounds=LanhuBounds(x=0, y=0, width=screen.width or 375, height=screen.height or 812),
        children=screen.layers,
    )
    if screen.background_color:
        from .models import LanhuFill
        root_layer.fills = [LanhuFill(type="solid", color=screen.background_color)]

    skeleton = infer_layer_layout(root_layer)
    skeleton.tag = "main"
    if "min-h-screen" not in skeleton.classes:
        skeleton.classes.append("min-h-screen")
    return skeleton

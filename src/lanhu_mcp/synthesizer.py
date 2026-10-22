"""智能视觉摘要与组件聚拢引擎 (Visual Synthesizer)

解决痛点：
1. 原始图层树庞大、嵌套深、无效图层多，LLM 难以一眼把握整体结构；
2. Sketch/Figma 中按钮通常被拆分为分离的 Background Shape 和 Text 图层，导致样式被割裂；
3. 画板逻辑像素与 Retina 导出尺寸可能存在缩放偏差，自动校正真实物理/逻辑基准；
4. 缺乏针对声明式 UI（Jetpack Compose / Flutter / React）的直观组件清单与布局蓝图。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import LanhuBounds, LanhuColor, LanhuLayer, LanhuScreen


def fix_screen_dimensions(screen: LanhuScreen) -> None:
    """校正设计图的实际尺寸基准。

    若蓝湖元信息的 width/height (如 187.5) 小于根图层 bounds (如 375.0)，
    自动采用根图层的实际逻辑像素基准，避免后续边距计算失真。
    """
    if not screen.layers:
        return

    root = screen.layers[0]
    if root.bounds and root.bounds.width > 0 and root.bounds.height > 0:
        root_w = root.bounds.width
        root_h = root.bounds.height
        if screen.width is None or root_w > screen.width:
            screen.width = root_w
        if screen.height is None or root_h > screen.height:
            screen.height = root_h


def count_total_layers(layers: list[LanhuLayer]) -> int:
    """递归统计图层树中全部节点总数"""
    count = 0
    for l in layers:
        count += 1 + count_total_layers(l.children)
    return count


def _color_to_hex_str(color: Optional[LanhuColor]) -> Optional[str]:
    """颜色格式化为统一的 16 进制字符串（若含透明度则返回 #RRGGBBAA）"""
    if not color:
        return None
    return color.to_hex(include_alpha=True)


def _flatten_layers_with_parents(
    layers: list[LanhuLayer], parent: Optional[LanhuLayer] = None
) -> list[tuple[LanhuLayer, Optional[LanhuLayer]]]:
    """平铺所有图层，附带其直接父图层引用"""
    out: list[tuple[LanhuLayer, Optional[LanhuLayer]]] = []
    for l in layers:
        out.append((l, parent))
        out.extend(_flatten_layers_with_parents(l.children, l))
    return out


def synthesize_visual_summary(screen: LanhuScreen) -> dict[str, Any]:
    """从设计图图层树中智能提炼高保真视觉摘要与语义化组件蓝图"""
    fix_screen_dimensions(screen)
    total_layers = count_total_layers(screen.layers)

    canvas_w = screen.width or 375.0
    canvas_h = screen.height or 812.0

    flattened = _flatten_layers_with_parents(screen.layers)

    # 1. 查找全局页面底色
    page_bg: Optional[str] = None
    if screen.background_color:
        page_bg = _color_to_hex_str(screen.background_color)
    else:
        for l, _ in flattened:
            if l.bounds and l.bounds.width >= canvas_w * 0.95 and l.bounds.height >= canvas_h * 0.95:
                if l.fills:
                    f = l.fills[0]
                    if f.color:
                        page_bg = _color_to_hex_str(f.color)
                        break

    # 2. 识别背景氛围大图（如顶部大背景图片）
    atmosphere_layers: list[dict[str, Any]] = []
    for l, _ in flattened:
        if l.bounds and l.bounds.width >= canvas_w * 0.9 and 200.0 <= l.bounds.height <= canvas_h * 0.8:
            name_lower = l.name.lower()
            if any(k in name_lower for k in ("bg", "background", "背景", "banner", "header_bg", "氛围")):
                res_name = re.sub(r"[^a-zA-Z0-9_]", "_", l.name).lower()
                atmosphere_layers.append({
                    "name": l.name,
                    "bounds": {"x": l.bounds.x, "y": l.bounds.y, "width": l.bounds.width, "height": l.bounds.height},
                    "recommended_compose": f"Image(painter = painterResource(R.drawable.{res_name}), contentDescription = null, contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth().height({int(l.bounds.height)}.dp).align(Alignment.TopCenter))",
                })

    # 3. 识别按钮组件（智能聚拢 Background Shape + Text，去重与去空）
    buttons: list[dict[str, Any]] = []
    button_text_ids: set[str] = set()
    seen_button_signatures: set[str] = set()

    for l, parent in flattened:
        name_lower = l.name.lower()
        is_button_name = any(k in name_lower for k in ("button", "btn", "按钮", "强按钮", "文字按钮"))

        # 容器自身是 Button 命名，其子节点包含文本和背景形状
        if is_button_name and l.children and l.bounds:
            # 查找内部文本
            sub_flat = _flatten_layers_with_parents(l.children, l)
            btn_text_layer = next((c for c, _ in sub_flat if c.text_content and c.text_content.strip()), None)

            # 查找背景形状（包含 fill、border、radius 的 shape）
            btn_bg_shape = next((c for c, _ in sub_flat if c.fills or c.border_radius), None)

            if btn_text_layer and btn_text_layer.text_content:
                text_str = btn_text_layer.text_content.strip()
                # 过滤无意义空白按钮
                if not text_str:
                    continue

                sig = f"{text_str}_{int(l.bounds.y)}"
                if sig in seen_button_signatures:
                    continue
                seen_button_signatures.add(sig)

                button_text_ids.add(btn_text_layer.id)
                t_font = btn_text_layer.font
                t_size = t_font.size if t_font and t_font.size else 16.0
                t_weight = t_font.weight if t_font and t_font.weight else "600"
                t_color = _color_to_hex_str(t_font.color) if t_font else "#FFFFFF"

                bg_color = None
                border_radius = None
                border_color = None
                border_width = None

                if btn_bg_shape:
                    if btn_bg_shape.fills and btn_bg_shape.fills[0].color:
                        bg_color = _color_to_hex_str(btn_bg_shape.fills[0].color)
                    border_radius = btn_bg_shape.border_radius
                    if btn_bg_shape.borders:
                        border_color = _color_to_hex_str(btn_bg_shape.borders[0].color)
                        border_width = btn_bg_shape.borders[0].width

                # 兜底从父容器自身取样式
                if not bg_color and l.fills and l.fills[0].color:
                    bg_color = _color_to_hex_str(l.fills[0].color)
                if border_radius is None:
                    border_radius = l.border_radius or 0.0

                b_w = l.bounds.width
                b_h = l.bounds.height
                is_full_width = b_w >= (canvas_w - 48.0)

                buttons.append({
                    "id": l.id,
                    "name": l.name,
                    "text": text_str,
                    "bounds": {"x": l.bounds.x, "y": l.bounds.y, "width": b_w, "height": b_h},
                    "background_color": bg_color,
                    "border_radius": border_radius,
                    "border": {"color": border_color, "width": border_width} if border_color else None,
                    "text_style": {
                        "size": t_size,
                        "weight": t_weight,
                        "color": t_color,
                    },
                    "is_full_width": is_full_width,
                    "recommended_compose": _generate_compose_button_code(
                        text_str, b_w, b_h, bg_color, border_radius, t_size, t_weight, t_color, is_full_width
                    ),
                })

    # 4. 识别协议与勾选行（Agreement Row）
    agreement_rows: list[dict[str, Any]] = []
    agreement_text_ids: set[str] = set()
    for l, _ in flattened:
        if l.text_content and ("已阅读" in l.text_content or "协议" in l.text_content or "同意" in l.text_content):
            agreement_text_ids.add(l.id)
            agreement_rows.append({
                "text": l.text_content,
                "bounds": {"x": l.bounds.x, "y": l.bounds.y, "width": l.bounds.width, "height": l.bounds.height} if l.bounds else None,
                "color": _color_to_hex_str(l.font.color) if l.font else None,
                "size": l.font.size if l.font else 12.0,
            })

    # 5. 识别导航栏与返回键（Navigation / TopBar）并去重
    navigation_items: list[dict[str, Any]] = []
    seen_nav_boxes: list[LanhuBounds] = []
    for l, _ in flattened:
        if l.bounds and l.bounds.y <= 90.0:
            name_lower = l.name.lower()
            if any(k in name_lower for k in ("back", "返回", "appback")):
                # 去除同位置重复图层
                is_dup = any(
                    abs(b.x - l.bounds.x) < 5 and abs(b.y - l.bounds.y) < 5
                    for b in seen_nav_boxes
                )
                if not is_dup:
                    seen_nav_boxes.append(l.bounds)
                    navigation_items.append({
                        "name": l.name,
                        "type": "back_button",
                        "bounds": {"x": l.bounds.x, "y": l.bounds.y, "width": l.bounds.width, "height": l.bounds.height},
                        "recommended_compose": "Image(painter = painterResource(R.drawable.ic_back), contentDescription = \"返回\", modifier = Modifier.size(24.dp).clickableNoRipple { navController.popBackStack() })",
                    })

    # 6. 提炼独立文本层（排除已被包含在按钮中的文本、协议中的文本以及顶部时间电量条）
    content_texts: list[dict[str, Any]] = []
    for l, _ in flattened:
        if not l.text_content or not l.text_content.strip():
            continue
        if l.id in button_text_ids:
            continue
        text_str = l.text_content.strip()
        # 排除系统状态栏模拟文本（如 9:41）
        if re.match(r"^\d{1,2}:\d{2}$", text_str):
            continue

        t_font = l.font
        t_size = t_font.size if t_font and t_font.size else 14.0
        t_weight = t_font.weight if t_font and t_font.weight else "400"
        t_color = _color_to_hex_str(t_font.color) if t_font else None

        role = "body"
        if t_size >= 22.0:
            role = "title_large"
        elif t_size >= 18.0:
            role = "title_medium"
        elif t_size <= 12.0:
            role = "caption"

        content_texts.append({
            "id": l.id,
            "text": text_str,
            "role": role,
            "size": t_size,
            "weight": t_weight,
            "color": t_color,
            "color_name": t_font.color.name if (t_font and t_font.color) else None,
            "bounds": {"x": l.bounds.x, "y": l.bounds.y, "width": l.bounds.width, "height": l.bounds.height} if l.bounds else None,
        })

    # 按纵坐标 Y 排序文本，保证自然视觉流向
    content_texts.sort(key=lambda t: (t["bounds"]["y"] if t.get("bounds") else 0))

    # 7. 切图与资产汇总
    asset_summaries: list[dict[str, Any]] = []
    for a in screen.assets:
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", a.name).lower()
        res_prefix = "ic_" if not clean_name.startswith(("ic_", "bg_")) else ""
        asset_summaries.append({
            "name": a.name,
            "format": a.format,
            "width": a.width,
            "height": a.height,
            "download_url": a.download_url,
            "recommended_res_name": f"{res_prefix}{clean_name}",
        })

    return {
        "canvas": {
            "name": screen.name,
            "width": canvas_w,
            "height": canvas_h,
            "background_color": page_bg or "#FFFFFF",
            "aspect_ratio": f"{canvas_w}:{canvas_h}",
            "device_class": "mobile_portrait" if canvas_h > canvas_w else "desktop_landscape",
        },
        "atmosphere_background": atmosphere_layers,
        "navigation": navigation_items,
        "buttons": buttons,
        "texts": content_texts,
        "agreement_rows": agreement_rows,
        "assets": asset_summaries,
        "total_layer_count": total_layers,
        "declarative_guidelines": _build_declarative_guidelines(canvas_w, canvas_h, buttons, content_texts),
    }


def _generate_compose_button_code(
    text: str,
    width: float,
    height: float,
    bg_color: Optional[str],
    radius: Optional[float],
    size: float,
    weight: str,
    color: str,
    is_full_width: bool,
) -> str:
    """生成 Compose 风格的高保真按钮实现代码模板"""
    h_dp = f"{int(height)}.dp"
    r_dp = f"{int(radius)}.dp" if radius else "8.dp"
    c_bg = f"Color(0x{bg_color[1:]})" if (bg_color and bg_color.startswith("#")) else "Color(0xFF00C18C)"
    if len(c_bg) == 15 and bg_color and len(bg_color) == 7:  # #RRGGBB -> 0xFFRRGGBB
        c_bg = f"Color(0xFF{bg_color[1:]})"
    elif bg_color and len(bg_color) == 9:  # #RRGGBBAA -> Color(0xAARRGGBB)
        # 转换 ARGB
        c_bg = f"Color(0x{bg_color[7:9]}{bg_color[1:7]})"

    c_text = "Color.White" if color.upper().startswith("#FFF") else f"Color(0xFF{color[1:7]})"
    fw = "FontWeight.SemiBold" if weight in ("600", "700", "bold") else "FontWeight.Normal"

    if is_full_width:
        return (
            f"Box(\n"
            f"    modifier = Modifier\n"
            f"        .fillMaxWidth()\n"
            f"        .padding(horizontal = 20.dp)\n"
            f"        .height({h_dp})\n"
            f"        .background({c_bg}, RoundedCornerShape({r_dp}))\n"
            f"        .clickableNoRipple {{ /* TODO: OnClick */ }},\n"
            f"    contentAlignment = Alignment.Center\n"
            f") {{\n"
            f"    Text(\"{text}\", color = {c_text}, fontSize = {int(size)}.sp, fontWeight = {fw})\n"
            f"}}"
        )
    return (
        f"Box(\n"
        f"    modifier = Modifier\n"
        f"        .height({h_dp})\n"
        f"        .wrapContentWidth()\n"
        f"        .padding(horizontal = 24.dp)\n"
        f"        .background({c_bg}, RoundedCornerShape({r_dp}))\n"
        f"        .clickableNoRipple {{ /* TODO: OnClick */ }},\n"
        f"    contentAlignment = Alignment.Center\n"
        f") {{\n"
        f"    Text(\"{text}\", color = {c_text}, fontSize = {int(size)}.sp, fontWeight = {fw})\n"
        f"}}"
    )


def _build_declarative_guidelines(
    canvas_w: float, canvas_h: float, buttons: list[dict], texts: list[dict]
) -> list[str]:
    """根据页面元素特征，生成声明式 UI 还原策略建议"""
    tips = [
        f"设计稿标准尺寸为 {int(canvas_w)}x{int(canvas_h)}，开发时禁止使用绝对坐标 (x, y) 写死组件位置；",
        "使用 Box 作为根容器层叠顶部背景氛围图与主内容层；",
        "主内容层使用 Column + statusBarsPadding() + navigationBarsPadding() 流式布局；",
    ]
    if len(buttons) >= 2:
        tips.append("检测到页面存在主要操作按钮与次要/底部操作按钮，推荐使用 Spacer(Modifier.weight(1f)) 弹性推到底部；")
    return tips

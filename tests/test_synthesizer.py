"""测试智能视觉摘要与组件聚拢引擎 (synthesizer)"""

from lanhu_mcp.models import (
    LanhuBounds,
    LanhuColor,
    LanhuFill,
    LanhuFont,
    LanhuLayer,
    LanhuScreen,
)
from lanhu_mcp.synthesizer import (
    count_total_layers,
    fix_screen_dimensions,
    synthesize_visual_summary,
)


def test_fix_screen_dimensions():
    # 测试 Retina 缩放纠正
    screen = LanhuScreen(id="s1", name="测试画板", width=187.5, height=406.0)
    root = LanhuLayer(
        id="root",
        name="root",
        type="artboard",
        bounds=LanhuBounds(x=0, y=0, width=375.0, height=812.0),
    )
    screen.layers = [root]

    fix_screen_dimensions(screen)
    assert screen.width == 375.0
    assert screen.height == 812.0


def test_count_total_layers():
    l3 = LanhuLayer(id="3", name="c3", type="text")
    l2 = LanhuLayer(id="2", name="c2", type="group", children=[l3])
    l1 = LanhuLayer(id="1", name="c1", type="group", children=[l2])
    assert count_total_layers([l1]) == 3


def test_synthesize_button_and_texts():
    # 构建一个包含 Background Shape + Text 的典型按钮
    bg_shape = LanhuLayer(
        id="shape1",
        name="按钮背景",
        type="shape",
        bounds=LanhuBounds(x=20, y=400, width=335, height=44),
        border_radius=12.0,
        fills=[LanhuFill(type="solid", color=LanhuColor(r=0, g=193, b=140, a=1.0))],
    )
    text_layer = LanhuLayer(
        id="text1",
        name="按钮文字",
        type="text",
        text_content="立即登录",
        bounds=LanhuBounds(x=150, y=412, width=75, height=20),
        font=LanhuFont(size=16.0, weight="600", color=LanhuColor(r=255, g=255, b=255, a=1.0)),
    )
    btn_group = LanhuLayer(
        id="btn_grp",
        name="强按钮/大尺寸",
        type="layer-group",
        bounds=LanhuBounds(x=20, y=400, width=335, height=44),
        children=[bg_shape, text_layer],
    )

    title_text = LanhuLayer(
        id="title",
        name="标题",
        type="text",
        text_content="欢迎来到山途",
        bounds=LanhuBounds(x=20, y=100, width=200, height=30),
        font=LanhuFont(size=24.0, weight="600", color=LanhuColor(r=230, g=232, b=242, a=0.9)),
    )

    root = LanhuLayer(
        id="root",
        name="root",
        type="artboard",
        bounds=LanhuBounds(x=0, y=0, width=375, height=812),
        children=[title_text, btn_group],
    )
    screen = LanhuScreen(id="s1", name="登录页", width=375, height=812, layers=[root])

    summary = synthesize_visual_summary(screen)

    assert summary["canvas"]["width"] == 375.0
    assert summary["canvas"]["height"] == 812.0

    # 验证按钮聚拢
    assert len(summary["buttons"]) == 1
    btn = summary["buttons"][0]
    assert btn["text"] == "立即登录"
    assert btn["background_color"] == "#00C18C"
    assert btn["border_radius"] == 12.0
    assert btn["is_full_width"] is True
    assert "Modifier" in btn["recommended_compose"]

    # 验证文本提取
    titles = [t for t in summary["texts"] if t["text"] == "欢迎来到山途"]
    assert len(titles) == 1
    assert titles[0]["size"] == 24.0
    assert titles[0]["weight"] == "600"

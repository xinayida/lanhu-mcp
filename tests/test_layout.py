import pytest
from lanhu_mcp.layout import infer_layer_layout, infer_screen_skeleton
from lanhu_mcp.models import (
    LanhuBounds,
    LanhuColor,
    LanhuFill,
    LanhuFont,
    LanhuLayer,
    LanhuScreen,
)


def test_infer_text_and_button_tags():
    # 测试大标题自动推断为 h1/h2
    title_layer = LanhuLayer(
        id="t1",
        name="Page Title",
        type="text",
        text_content="欢迎登录系统",
        font=LanhuFont(size=28.0, weight="bold"),
        bounds=LanhuBounds(x=20, y=40, width=200, height=36),
    )
    node_t = infer_layer_layout(title_layer)
    assert node_t.tag == "h1"
    assert node_t.text == "欢迎登录系统"

    # 测试按钮标签推断
    btn_layer = LanhuLayer(
        id="b1",
        name="submit_button",
        type="rect",
        border_radius=12.0,
        fills=[LanhuFill(type="solid", color=LanhuColor(r=69, g=140, b=255, a=1.0))],
        bounds=LanhuBounds(x=20, y=200, width=335, height=48),
    )
    node_b = infer_layer_layout(btn_layer)
    assert node_b.tag == "button"
    assert "rounded-xl" in node_b.classes
    assert "bg-[#458CFF]" in node_b.classes


def test_infer_vertical_column_flow():
    # 父容器包含垂直排列的两个卡片
    parent = LanhuLayer(
        id="p1",
        name="Form Container",
        type="group",
        bounds=LanhuBounds(x=0, y=0, width=375, height=500),
        children=[
            LanhuLayer(
                id="c1",
                name="Input 1",
                type="rect",
                bounds=LanhuBounds(x=20, y=30, width=335, height=50),
            ),
            LanhuLayer(
                id="c2",
                name="Input 2",
                type="rect",
                bounds=LanhuBounds(x=20, y=100, width=335, height=50),  # gap = 100 - (30+50) = 20
            ),
        ],
    )

    node = infer_layer_layout(parent)
    assert node.direction == "column"
    assert "flex flex-col" in node.classes[0]
    assert node.gap == 20.0
    assert "gap-5" in node.classes
    assert len(node.children) == 2


def test_infer_horizontal_row_flow():
    # 底部栏两个并排按钮
    parent = LanhuLayer(
        id="bar",
        name="Action Bar",
        type="group",
        bounds=LanhuBounds(x=0, y=0, width=375, height=60),
        children=[
            LanhuLayer(
                id="b1",
                name="Cancel Button",
                type="rect",
                bounds=LanhuBounds(x=20, y=10, width=160, height=40),
            ),
            LanhuLayer(
                id="b2",
                name="Confirm Button",
                type="rect",
                bounds=LanhuBounds(x=195, y=10, width=160, height=40),  # gap = 195 - (20+160) = 15
            ),
        ],
    )

    node = infer_layer_layout(parent)
    assert node.direction == "row"
    assert "flex flex-row" in node.classes[0]
    assert node.gap == 15.0
    assert len(node.children) == 2


def test_infer_screen_skeleton():
    screen = LanhuScreen(
        id="s1",
        name="Login Screen",
        width=375,
        height=812,
        layers=[
            LanhuLayer(
                id="l1",
                name="Header",
                type="rect",
                bounds=LanhuBounds(x=0, y=0, width=375, height=88),
            ),
            LanhuLayer(
                id="l2",
                name="Content",
                type="rect",
                bounds=LanhuBounds(x=0, y=100, width=375, height=400),
            ),
        ],
    )
    skeleton = infer_screen_skeleton(screen)
    assert skeleton.tag == "main"
    assert "min-h-screen" in skeleton.classes
    assert skeleton.direction == "column"
    assert len(skeleton.children) == 2

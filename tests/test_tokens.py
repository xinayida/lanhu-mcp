import pytest
from lanhu_mcp.models import (
    LanhuBorder,
    LanhuBounds,
    LanhuColor,
    LanhuFill,
    LanhuFont,
    LanhuLayer,
    LanhuScreen,
    LanhuShadow,
)
from lanhu_mcp.tokens import extract_design_tokens


def test_extract_design_tokens():
    # 创建模拟图层
    screen = LanhuScreen(
        id="s1",
        name="Home Screen",
        background_color=LanhuColor(r=245, g=245, b=245, a=1.0, name="Bg/Grey"),
        layers=[
            LanhuLayer(
                id="l1",
                name="Header Card",
                type="rect",
                border_radius=16.0,
                fills=[
                    LanhuFill(
                        type="solid",
                        color=LanhuColor(r=255, g=255, b=255, a=1.0, name="Neutral/White"),
                    )
                ],
                shadows=[
                    LanhuShadow(x=0, y=4, blur=12, spread=0, color=LanhuColor(r=0, g=0, b=0, a=0.1))
                ],
                children=[
                    LanhuLayer(
                        id="l2",
                        name="Title",
                        type="text",
                        font=LanhuFont(
                            family="PingFang SC",
                            size=20.0,
                            weight="600",
                            color=LanhuColor(r=34, g=34, b=34, a=1.0, name="Text/Main"),
                        ),
                    ),
                    LanhuLayer(
                        id="l3",
                        name="Action Button",
                        type="rect",
                        border_radius=8.0,
                        fills=[
                            LanhuFill(
                                type="solid",
                                color=LanhuColor(r=69, g=140, b=255, a=1.0, name="Brand/Primary"),
                            )
                        ],
                        borders=[
                            LanhuBorder(
                                width=1.0,
                                color=LanhuColor(r=69, g=140, b=255, a=1.0),
                            )
                        ],
                    ),
                ],
            )
        ],
    )

    tokens = extract_design_tokens(screen)

    # 1. 验证颜色提取
    hex_list = [c.hex for c in tokens.colors]
    assert "#FFFFFF" in hex_list
    assert "#458CFF" in hex_list
    assert "#222222" in hex_list

    # 验证规范命名的映射
    brand_token = next(c for c in tokens.colors if c.hex == "#458CFF")
    assert "brand-primary" in brand_token.token_name
    assert brand_token.raw_name == "Brand/Primary"

    # 2. 验证字体规格
    assert "PingFang SC" in tokens.font_families
    assert 20.0 in tokens.font_sizes
    assert "600" in tokens.font_weights

    # 3. 验证圆角规格
    assert 8.0 in tokens.radii
    assert 16.0 in tokens.radii

    # 4. 验证 CSS 变量输出
    css_vars = tokens.to_css_variables()
    assert ":root {" in css_vars
    assert "--color-brand-primary: #458CFF;" in css_vars
    assert "--font-size-1: 20.0px;" in css_vars
    assert "--radius-1: 8.0px;" in css_vars

    # 5. 验证 Tailwind 配置输出
    tw = tokens.to_tailwind_config()
    assert "colors" in tw
    assert "brand_primary" in tw["colors"] or "color_brand_primary" in tw["colors"]

    # 6. 验证 W3C tokens
    w3c = tokens.to_w3c_tokens()
    assert "color" in w3c
    assert "fontSize" in w3c

import pytest
from lanhu_mcp.client import slice_utf16_text


def test_slice_utf16_ascii():
    text = "Hello World"
    # Slice "World" (start=6, length=5)
    assert slice_utf16_text(text, 6, 5) == "World"
    assert slice_utf16_text(text, 0, 5) == "Hello"


def test_slice_utf16_cjk():
    text = "设计稿标注提取"
    assert slice_utf16_text(text, 0, 3) == "设计稿"
    assert slice_utf16_text(text, 3, 2) == "标注"


def test_slice_utf16_with_emoji():
    # Emoji '🚀' (U+1F680) is an astral character: 1 Python character, but 2 UTF-16 code units!
    text = "A🚀B"
    # 'A' is at offset 0, len 1
    assert slice_utf16_text(text, 0, 1) == "A"
    # '🚀' is at offset 1, len 2
    assert slice_utf16_text(text, 1, 2) == "🚀"
    # 'B' is at offset 3, len 1
    assert slice_utf16_text(text, 3, 1) == "B"


def test_slice_utf16_multiple_emojis():
    text = "🎉欢迎🎨蓝湖"
    # '🎉' (len 2) + '欢迎' (len 2) + '🎨' (len 2) + '蓝湖' (len 2)
    assert slice_utf16_text(text, 0, 2) == "🎉"
    assert slice_utf16_text(text, 2, 2) == "欢迎"
    assert slice_utf16_text(text, 4, 2) == "🎨"
    assert slice_utf16_text(text, 6, 2) == "蓝湖"

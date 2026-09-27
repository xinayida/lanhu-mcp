import io
import pytest
from PIL import Image
import httpx
from unittest.mock import MagicMock
from lanhu_mcp.client import LanhuClient
from lanhu_mcp.models import LanhuAsset, LanhuScreen


def test_screen_oversized_flag():
    # Regular screen
    normal_screen = LanhuScreen(id="1", name="Normal", width=1920, height=1080)
    assert not normal_screen.is_oversized

    # Oversized screen (>4096px or >25M pixels)
    oversized_screen = LanhuScreen(id="2", name="Long Page", width=1920, height=15000)
    assert oversized_screen.is_oversized


@pytest.mark.asyncio
async def test_download_asset_webp_conversion_safe(tmp_path):
    mock_auth = MagicMock()
    client = LanhuClient(mock_auth)

    # Create a small valid test PNG in memory
    img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    asset = LanhuAsset(id="a1", name="icon_test", download_url="https://example.com/icon.png")

    client._download_http_client = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=png_bytes))
    )

    out_file = await client.download_asset(asset, str(tmp_path))
    assert out_file.endswith(".webp")
    with Image.open(out_file) as saved_img:
        assert saved_img.format == "WEBP"
        assert saved_img.size == (100, 100)


@pytest.mark.asyncio
async def test_download_asset_svg_saved_directly(tmp_path):
    mock_auth = MagicMock()
    client = LanhuClient(mock_auth)

    svg_content = b"<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24'></svg>"
    asset = LanhuAsset(id="s1", name="icon_arrow", format="svg", download_url="https://example.com/arrow.svg")

    client._download_http_client = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=svg_content))
    )

    out_file = await client.download_asset(asset, str(tmp_path))
    assert out_file.endswith(".svg")
    assert (tmp_path / "icon_arrow.svg").read_bytes() == svg_content

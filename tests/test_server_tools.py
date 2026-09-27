import pytest
from unittest.mock import AsyncMock, patch
from lanhu_mcp.server import (
    lanhu_inspect_url,
    lanhu_get_screens,
    lanhu_get_annotations,
    lanhu_get_assets,
    _screen_summary,
    _screen_full,
)
from lanhu_mcp.models import LanhuScreen, LanhuAsset


def test_screen_summary_oversized():
    s = LanhuScreen(id="1", name="Normal", width=1920, height=1080)
    summary = _screen_summary(s)
    assert summary["is_oversized"] is False

    s_large = LanhuScreen(id="2", name="Long Page", width=1920, height=15000)
    summary_large = _screen_summary(s_large)
    assert summary_large["is_oversized"] is True


@pytest.mark.asyncio
async def test_server_inspect_url_invokes_client():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.inspect_url", new_callable=AsyncMock) as mock_inspect:
        mock_inspect.return_value = {"type": "stage_project", "screen_count": 2}
        url = "https://lanhuapp.com/web/#/item/project/stage?tid=t1&pid=p1"
        res = await lanhu_inspect_url(url=url)
        assert res["type"] == "stage_project"
        mock_inspect.assert_awaited_once_with(url)


@pytest.mark.asyncio
async def test_server_get_screens_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_screens", new_callable=AsyncMock) as mock_get_screens:
        mock_get_screens.return_value = [
            LanhuScreen(id="img1", name="Card", width=300, height=400)
        ]
        url = "https://lanhuapp.com/web/#/item/project/stage?tid=t1&pid=p1"
        res = await lanhu_get_screens(url=url)
        assert len(res) == 1
        assert res[0]["id"] == "img1"
        mock_get_screens.assert_awaited_once_with("p1", "t1")


@pytest.mark.asyncio
async def test_server_get_annotations_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_annotations", new_callable=AsyncMock) as mock_anno:
        mock_anno.return_value = LanhuScreen(id="img1", name="Detail", width=375, height=812)
        url = "https://lanhuapp.com/web/#/item/project/detailDetach?pid=p1&image_id=img1"
        res = await lanhu_get_annotations(url=url)
        assert res["id"] == "img1"
        mock_anno.assert_awaited_once_with("p1", "img1", None)

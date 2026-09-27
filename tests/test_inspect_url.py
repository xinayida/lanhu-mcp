import pytest
from unittest.mock import AsyncMock, MagicMock
from lanhu_mcp.client import LanhuClient
from lanhu_mcp.models import LanhuScreen, LanhuAsset


@pytest.mark.asyncio
async def test_client_inspect_url_stage():
    mock_auth = MagicMock()
    client = LanhuClient(mock_auth)

    # Mock get_screens
    mock_screens = [
        LanhuScreen(id="img1", name="Home", width=375, height=812, project_id="p1")
    ]
    client.get_screens = AsyncMock(return_value=mock_screens)

    result = await client.inspect_url("https://lanhuapp.com/web/#/item/project/stage?tid=t1&pid=p1")
    assert result["type"] == "stage_project"
    assert len(result["screens"]) == 1
    assert result["screens"][0]["id"] == "img1"
    client.get_screens.assert_awaited_once_with(project_id="p1", team_id="t1")


@pytest.mark.asyncio
async def test_client_inspect_url_detail_detach():
    mock_auth = MagicMock()
    client = LanhuClient(mock_auth)

    mock_screen = LanhuScreen(
        id="img1", name="Detail", width=375, height=812, project_id="p1",
        assets=[LanhuAsset(id="a1", name="logo", format="webp")]
    )
    client.get_annotations = AsyncMock(return_value=mock_screen)

    result = await client.inspect_url("https://lanhuapp.com/web/#/item/project/detailDetach?pid=p1&image_id=img1")
    assert result["type"] == "screen_detail"
    assert result["screen"]["id"] == "img1"
    client.get_annotations.assert_awaited_once_with(project_id="p1", image_id="img1", team_id=None)

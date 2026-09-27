import pytest
from unittest.mock import AsyncMock, patch
from lanhu_mcp.server import (
    lanhu_inspect_url,
    lanhu_get_screens,
    lanhu_get_annotations,
    lanhu_get_assets,
    lanhu_list_product_documents,
    lanhu_get_pages,
    lanhu_get_page_content,
    lanhu_batch_export_assets,
    lanhu_get_design_tokens,
    lanhu_get_layout_skeleton,
    _screen_summary,
    _screen_full,
)
from lanhu_mcp.models import (
    LanhuScreen,
    LanhuAsset,
    LanhuProductDoc,
    LanhuAxurePage,
    LanhuDesignTokens,
    LanhuColorToken,
    LanhuLayoutNode,
)


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


@pytest.mark.asyncio
async def test_server_list_product_documents_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_product_documents", new_callable=AsyncMock) as mock_docs:
        mock_docs.return_value = [
            LanhuProductDoc(id="doc-1", name="PRD", project_id="p1")
        ]
        url = "https://lanhuapp.com/web/#/item/project/stage?tid=t1&pid=p1"
        res = await lanhu_list_product_documents(url=url)
        assert len(res) == 1
        assert res[0]["id"] == "doc-1"
        mock_docs.assert_awaited_once_with("p1", "t1")


@pytest.mark.asyncio
async def test_server_get_pages_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_axure_sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = {
            "doc_id": "doc-1",
            "doc_name": "PRD",
            "project_id": "p1",
            "version": "1.0",
            "page_count": 2,
            "pages": [{"name": "首页"}],
        }
        url = "https://lanhuapp.com/web/#/item/project/productDoc?pid=p1&doc_id=doc-1"
        res = await lanhu_get_pages(url=url)
        assert res["doc_id"] == "doc-1"
        assert res["page_count"] == 2
        mock_sitemap.assert_awaited_once_with("p1", "doc-1", None)


@pytest.mark.asyncio
async def test_server_get_page_content_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_axure_page_content", new_callable=AsyncMock) as mock_content:
        mock_content.return_value = LanhuAxurePage(
            id="page-1",
            name="登录页",
            filename="登录页.html",
            text_content=["需求描述1"],
            annotations=[{"label": "输入框", "note": "必填"}],
        )
        url = "https://lanhuapp.com/web/#/item/project/productDoc?pid=p1&doc_id=doc-1"
        res = await lanhu_get_page_content(page_name="登录页", url=url)
        assert res["name"] == "登录页"
        assert res["text_content"] == ["需求描述1"]
        mock_content.assert_awaited_once_with("p1", "doc-1", "登录页", None)


@pytest.mark.asyncio
async def test_server_batch_export_assets_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_assets", new_callable=AsyncMock) as mock_assets, \
         patch("lanhu_mcp.server._client.batch_download_assets", new_callable=AsyncMock) as mock_batch:
        mock_assets.return_value = [
            LanhuAsset(id="a1", name="icon", format="svg", download_url="http://example.com/icon.svg")
        ]
        mock_batch.return_value = {
            "total_count": 1,
            "success_count": 1,
            "assets": [{"name": "icon", "status": "success"}],
        }
        url = "https://lanhuapp.com/web/#/item/project/detailDetach?pid=p1&image_id=img1"
        res = await lanhu_batch_export_assets(url=url)
        assert res["total_count"] == 1
        assert res["success_count"] == 1
        mock_assets.assert_awaited_once_with("p1", "img1", None)


@pytest.mark.asyncio
async def test_server_get_design_tokens_with_formats():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_design_tokens", new_callable=AsyncMock) as mock_tokens:
        mock_tokens.return_value = LanhuDesignTokens(
            colors=[LanhuColorToken(token_name="color-primary", hex="#458CFF", rgba="rgba(69,140,255,1)")],
            font_sizes=[14.0, 16.0],
            radii=[8.0],
        )
        url = "https://lanhuapp.com/web/#/item/project/stage?tid=t1&pid=p1"

        # 默认 json 格式
        res_json = await lanhu_get_design_tokens(url=url, format="json")
        assert len(res_json["colors"]) == 1
        assert res_json["colors"][0]["token_name"] == "color-primary"

        # css 变量格式
        res_css = await lanhu_get_design_tokens(url=url, format="css")
        assert res_css["format"] == "css"
        assert "--color-primary: #458CFF;" in res_css["code"]

        # tailwind 配置格式
        res_tw = await lanhu_get_design_tokens(url=url, format="tailwind")
        assert res_tw["format"] == "tailwind"
        assert "primary" in res_tw["config"]["colors"]


@pytest.mark.asyncio
async def test_server_get_layout_skeleton_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.get_layout_skeleton", new_callable=AsyncMock) as mock_skeleton:
        mock_skeleton.return_value = LanhuLayoutNode(
            id="root",
            name="Main Page",
            tag="main",
            display="flex",
            direction="column",
            classes=["flex", "flex-col", "gap-4"],
        )
        url = "https://lanhuapp.com/web/#/item/project/detailDetach?pid=p1&image_id=img1"
        res = await lanhu_get_layout_skeleton(url=url)
        assert res["tag"] == "main"
        assert res["direction"] == "column"
        assert "flex-col" in res["classes"]
        mock_skeleton.assert_awaited_once_with("p1", "img1", team_id=None)



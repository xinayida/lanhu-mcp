import pytest
from unittest.mock import AsyncMock, patch
from mcp.server.mcpserver.exceptions import ToolError

from lanhu_mcp.client import LanhuClient
from lanhu_mcp.models import LanhuProject, LanhuScreen
from lanhu_mcp.server import lanhu_search_team_images


@pytest.fixture
def mock_client():
    auth = AsyncMock()
    auth.is_authenticated = True
    auth.headers = {}
    return LanhuClient(auth)


@pytest.mark.asyncio
async def test_search_team_images_success(mock_client):
    # 模拟团队有两个项目：项目A 和 项目B
    projects = [
        LanhuProject(id="p1", name="项目 A", team_id="t1"),
        LanhuProject(id="p2", name="项目 B", team_id="t1"),
    ]
    # 项目A 下有 登录页、启动页
    screens_p1 = [
        LanhuScreen(id="img1", name="登录页", project_id="p1", width=375, height=812, thumbnail_url="https://img/1.png", updated_at="2026-11-01"),
        LanhuScreen(id="img2", name="启动页", project_id="p1", width=375, height=812),
    ]
    # 项目B 下有 设置页、个人中心
    screens_p2 = [
        LanhuScreen(id="img3", name="设置页", project_id="p2", width=375, height=812, updated_at="2026-11-05"),
        LanhuScreen(id="img4", name="个人中心", project_id="p2", width=375, height=812),
    ]

    with patch.object(mock_client, "get_projects", new_callable=AsyncMock) as mock_get_proj, \
         patch.object(mock_client, "get_screens", new_callable=AsyncMock) as mock_get_screens:
        mock_get_proj.return_value = projects
        
        async def side_get_screens(project_id, team_id=None):
            if project_id == "p1":
                return screens_p1
            return screens_p2
        mock_get_screens.side_effect = side_get_screens

        # 搜索“设置”
        res = await mock_client.search_team_images(team_id="t1", keyword="设置")

        assert res["total_found"] == 1
        assert res["matched_count"] == 1
        assert res["has_more"] is False
        assert res["searched_projects_count"] == 2
        assert res["total_projects_count"] == 2
        assert len(res["failed_projects"]) == 0
        
        item = res["images"][0]
        assert item["image_id"] == "img3"
        assert item["image_name"] == "设置页"
        assert item["project_id"] == "p2"
        assert item["project_name"] == "项目 B"
        assert item["updated_at"] == "2026-11-05"
        assert "pid=p2" in item["url"]
        assert "image_id=img3" in item["url"]
        assert "tid=t1" in item["url"]


@pytest.mark.asyncio
async def test_search_team_images_limit_and_has_more(mock_client):
    projects = [
        LanhuProject(id="p1", name="项目 A", team_id="t1"),
    ]
    screens = [
        LanhuScreen(id=f"img_{i}", name=f"页面_{i}", project_id="p1")
        for i in range(10)
    ]

    with patch.object(mock_client, "get_projects", new_callable=AsyncMock) as mock_get_proj, \
         patch.object(mock_client, "get_screens", new_callable=AsyncMock) as mock_get_screens:
        mock_get_proj.return_value = projects
        mock_get_screens.return_value = screens

        # limit = 3
        res = await mock_client.search_team_images(team_id="t1", keyword="页面", limit=3)
        assert res["total_found"] == 10
        assert res["matched_count"] == 3
        assert res["has_more"] is True
        assert len(res["images"]) == 3


@pytest.mark.asyncio
async def test_search_team_images_partial_failure_tolerance(mock_client):
    # 模拟项目A 成功，项目B 报错（例如权限不足或网络异常）
    projects = [
        LanhuProject(id="p1", name="可访问项目", team_id="t1"),
        LanhuProject(id="p2", name="权限不足项目", team_id="t1"),
    ]
    screens_p1 = [
        LanhuScreen(id="img1", name="订单详情", project_id="p1"),
    ]

    with patch.object(mock_client, "get_projects", new_callable=AsyncMock) as mock_get_proj, \
         patch.object(mock_client, "get_screens", new_callable=AsyncMock) as mock_get_screens:
        mock_get_proj.return_value = projects

        async def side_get_screens(project_id, team_id=None):
            if project_id == "p1":
                return screens_p1
            raise RuntimeError("403 Forbidden: 没有该项目权限")
        mock_get_screens.side_effect = side_get_screens

        res = await mock_client.search_team_images(team_id="t1", keyword="订单")
        assert res["total_found"] == 1
        assert res["matched_count"] == 1
        assert res["searched_projects_count"] == 1
        assert res["total_projects_count"] == 2
        assert len(res["failed_projects"]) == 1
        assert res["failed_projects"][0]["project_id"] == "p2"
        assert res["failed_projects"][0]["project_name"] == "权限不足项目"
        assert "403 Forbidden" in res["failed_projects"][0]["error"]
        assert res["images"][0]["image_id"] == "img1"


@pytest.mark.asyncio
async def test_search_team_images_empty_projects(mock_client):
    with patch.object(mock_client, "get_projects", new_callable=AsyncMock) as mock_get_proj:
        mock_get_proj.return_value = []
        res = await mock_client.search_team_images(team_id="t_empty", keyword="test")
        assert res["total_found"] == 0
        assert res["matched_count"] == 0
        assert res["has_more"] is False
        assert res["searched_projects_count"] == 0
        assert res["total_projects_count"] == 0
        assert res["images"] == []


@pytest.mark.asyncio
async def test_server_search_team_images_with_url():
    with patch("lanhu_mcp.server._ensure_auth"), \
         patch("lanhu_mcp.server._client.search_team_images", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "total_found": 1,
            "matched_count": 1,
            "has_more": False,
            "searched_projects_count": 1,
            "total_projects_count": 1,
            "failed_projects": [],
            "images": [{"image_id": "img1", "image_name": "支付页"}],
        }

        # 传入带有 tid 的 url
        url = "https://lanhuapp.com/web/#/item/project/stage?tid=team_abc&pid=p1"
        res = await lanhu_search_team_images(keyword="支付", url=url)
        assert res["total_found"] == 1
        assert res["images"][0]["image_name"] == "支付页"
        mock_search.assert_awaited_once_with(team_id="team_abc", keyword="支付", limit=20)


@pytest.mark.asyncio
async def test_server_search_team_images_missing_team_id():
    with patch("lanhu_mcp.server._ensure_auth"):
        with pytest.raises(ToolError, match="缺少 team_id 参数"):
            await lanhu_search_team_images(keyword="支付")

import pytest
from unittest.mock import AsyncMock, MagicMock
from lanhu_mcp.client import LanhuClient, extract_axure_pages_from_sitemap, extract_axure_page_text, parse_axure_data_js
from lanhu_mcp.models import LanhuProductDoc


def test_extract_axure_pages_from_sitemap():
    sitemap = {
        "rootNodes": [
            {
                "pageName": "系统说明",
                "type": "Wireframe",
                "url": "系统说明.html",
                "id": "page-1",
                "children": [],
            },
            {
                "pageName": "用户模块",
                "type": "Folder",
                "url": "",
                "id": "folder-1",
                "children": [
                    {
                        "pageName": "登录页",
                        "type": "Wireframe",
                        "url": "登录页.html",
                        "id": "page-2",
                    }
                ],
            },
        ]
    }
    pages = extract_axure_pages_from_sitemap(sitemap)
    assert len(pages) == 2
    assert pages[0]["name"] == "系统说明"
    assert pages[0]["filename"] == "系统说明.html"
    assert pages[0]["folder"] == "根目录"

    assert pages[1]["name"] == "登录页"
    assert pages[1]["filename"] == "登录页.html"
    assert pages[1]["folder"] == "用户模块"


def test_extract_axure_page_text_from_html():
    html_sample = """
    <!DOCTYPE html>
    <html>
      <head><title>测试页面</title></head>
      <body>
        <div id="u0" class="ax_default text">
          <p><span>这是第一行需求描述</span></p>
        </div>
        <div id="u1" class="ax_default box_1">
          <div id="u1_div"></div>
          <div id="u1_text" class="text">
            <p><span>用户名规则：&#x5FC5;&#x586B;&#xFF0C;4-20&#x4F4D;</span></p>
          </div>
        </div>
      </body>
    </html>
    """
    texts = extract_axure_page_text(html_sample)
    assert len(texts) == 2
    assert "这是第一行需求描述" in texts[0]
    assert "用户名规则：必填，4-20位" in texts[1]


def test_parse_axure_data_js():
    data_js_sample = """
    $axure.loadCurrentPage(lanhu_Axure_Mapping_Data({
        "url": "login.html",
        "page": {
            "name": "登录页",
            "annotations": [
                {
                    "fn": 1,
                    "label": "密码输入框",
                    "注释": "支持6-20位字母数字混合",
                    "ownerId": "obj-1"
                }
            ],
            "notes": {
                "描述": "页面原型交互说明"
            },
            "diagram": {
                "objects": [
                    {
                        "id": "obj-1",
                        "friendlyType": "Text Field",
                        "label": "passwordInput"
                    }
                ]
            }
        }
    }))
    """
    parsed = parse_axure_data_js(data_js_sample)
    assert parsed is not None
    assert parsed["name"] == "登录页"
    assert len(parsed["annotations"]) == 1
    assert parsed["annotations"][0]["label"] == "密码输入框"
    assert parsed["annotations"][0]["note"] == "支持6-20位字母数字混合"
    assert parsed["notes"]["描述"] == "页面原型交互说明"
    assert len(parsed["objects"]) == 1


@pytest.mark.asyncio
async def test_client_get_product_documents():
    client = LanhuClient(auth=MagicMock())
    mock_resp = [
        {
            "id": "doc_123",
            "name": "用户中心PRD",
            "type": "axure",
            "last_version_num": 3,
            "latest_version": "v3",
            "create_time": "2026-01-01",
            "update_time": "2026-01-02",
        }
    ]
    client._get = AsyncMock(return_value=mock_resp)
    docs = await client.get_product_documents("proj_1", "team_1")
    assert len(docs) == 1
    assert docs[0].id == "doc_123"
    assert docs[0].name == "用户中心PRD"
    assert "pid=proj_1" in (docs[0].url or "")


@pytest.mark.asyncio
async def test_client_get_axure_page_content_flow():
    client = LanhuClient(auth=MagicMock())
    # Mock sitemap
    client.get_axure_sitemap = AsyncMock(return_value={
        "doc_id": "doc_1",
        "project_id": "proj_1",
        "doc_name": "系统PRD",
        "base_url": "https://oss.lanhuapp.com/test",
        "pages": [
            {
                "id": "p1",
                "name": "登录页",
                "filename": "login.html",
                "folder": "用户中心",
                "path": "用户中心/登录页",
                "level": 1,
            }
        ],
        "pages_manifest": {
            "login.html": {
                "html": {"sign_md5": "md5_login_html"},
                "dataJs": {"sign_md5": "md5_login_js"},
            }
        },
    })

    # Mock download http client responses
    html_text = '<div class="text"><p><span>用户名与密码必填</span></p></div>'
    js_text = '$axure.loadCurrentPage({"page": {"name": "登录页", "annotations": [{"label": "登录按钮", "note": "点击跳转首页"}]}})'

    mock_http_client = AsyncMock()
    async def mock_get(url):
        m = MagicMock()
        m.status_code = 200
        if "html" in url:
            m.text = html_text
        else:
            m.text = js_text
        return m
    mock_http_client.get = mock_get
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    client._download_http_client = MagicMock(return_value=mock_http_client)

    page = await client.get_axure_page_content("proj_1", "doc_1", "登录页")
    assert page.name == "登录页"
    assert page.folder == "用户中心"
    assert "用户名与密码必填" in page.text_content
    assert len(page.annotations) == 1
    assert page.annotations[0]["label"] == "登录按钮"
    assert page.annotations[0]["note"] == "点击跳转首页"


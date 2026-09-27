import pytest
from lanhu_mcp.url_parser import parse_lanhu_url
from lanhu_mcp.models import LanhuParsedURL


def test_parse_stage_project_url():
    url = "https://lanhuapp.com/web/#/item/project/stage?tid=team123&pid=prj456"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "stage_project"
    assert parsed.team_id == "team123"
    assert parsed.project_id == "prj456"
    assert parsed.image_id is None


def test_parse_stage_screen_url():
    url = "https://lanhuapp.com/web/#/item/project/stage?tid=team123&pid=prj456&image_id=img789"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "screen_detail"
    assert parsed.team_id == "team123"
    assert parsed.project_id == "prj456"
    assert parsed.image_id == "img789"


def test_parse_detail_detach_url():
    url = "https://lanhuapp.com/web/#/item/project/detailDetach?pid=prj456&image_id=img789"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "screen_detail"
    assert parsed.project_id == "prj456"
    assert parsed.image_id == "img789"
    assert parsed.team_id is None


def test_parse_detail_detach_with_tid():
    url = "https://lanhuapp.com/web/#/item/project/detailDetach?tid=team123&pid=prj456&image_id=img789"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "screen_detail"
    assert parsed.team_id == "team123"
    assert parsed.project_id == "prj456"
    assert parsed.image_id == "img789"


def test_parse_product_doc_url():
    url = "https://lanhuapp.com/web/#/item/project/product?tid=team123&pid=prj456&docId=doc789&versionId=v1"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "product_doc"
    assert parsed.team_id == "team123"
    assert parsed.project_id == "prj456"
    assert parsed.doc_id == "doc789"
    assert parsed.version_id == "v1"


def test_parse_invite_url():
    url = "https://lanhuapp.com/link/#/invite?sid=abc123xyz"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "invite_link"
    assert parsed.sid == "abc123xyz"


def test_parse_query_string():
    url = "?tid=team123&pid=prj456&image_id=img789"
    parsed = parse_lanhu_url(url)
    assert parsed.url_type == "screen_detail"
    assert parsed.team_id == "team123"
    assert parsed.project_id == "prj456"
    assert parsed.image_id == "img789"


def test_parse_invalid_url():
    parsed = parse_lanhu_url("not_a_valid_url")
    assert parsed.url_type == "unknown"

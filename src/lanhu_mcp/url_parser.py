"""蓝湖 URL 解析器

支持解析多种蓝湖 URL 格式：
1. 设计项目画板列表页:
   https://lanhuapp.com/web/#/item/project/stage?tid=xxx&pid=xxx
2. 独立画板详情页 (detailDetach):
   https://lanhuapp.com/web/#/item/project/detailDetach?pid=xxx&image_id=xxx
   https://lanhuapp.com/web/#/item/project/detailDetach?tid=xxx&pid=xxx&image_id=xxx
3. 画板详情页 (stage 带 image_id):
   https://lanhuapp.com/web/#/item/project/stage?tid=xxx&pid=xxx&image_id=xxx
4. 产品/Axure原型文档页:
   https://lanhuapp.com/web/#/item/project/product?tid=xxx&pid=xxx&docId=xxx
5. 邀请/分享链接:
   https://lanhuapp.com/link/#/invite?sid=xxx
   https://lanhuapp.com/link/#/share?sid=xxx
6. 纯查询字符串:
   ?tid=xxx&pid=xxx&image_id=xxx
   tid=xxx&pid=xxx&image_id=xxx
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from .models import LanhuParsedURL


def parse_lanhu_url(url: str) -> LanhuParsedURL:
    """解析蓝湖 URL，提取项目 ID、团队 ID、设计图 ID、文档 ID 等信息。"""
    raw_url = (url or "").strip()
    if not raw_url:
        return LanhuParsedURL(raw_url=raw_url, url_type="unknown")

    fragment = ""
    query_str = ""
    path = ""

    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        parsed = urlparse(raw_url)
        path = parsed.path
        fragment = parsed.fragment
        query_str = parsed.query
    elif raw_url.startswith("#"):
        fragment = raw_url[1:]
    elif raw_url.startswith("?"):
        query_str = raw_url[1:]
    elif "=" in raw_url and not raw_url.startswith("/"):
        query_str = raw_url
    else:
        fragment = raw_url

    fragment_path = fragment
    if "?" in fragment:
        fragment_path, frag_query = fragment.split("?", 1)
        if query_str:
            query_str = f"{query_str}&{frag_query}"
        else:
            query_str = frag_query

    params: dict[str, str] = {}
    if query_str:
        for k, v in parse_qs(query_str, keep_blank_values=True).items():
            if v:
                params[k] = v[-1]

    team_id = params.get("tid") or params.get("team_id")
    project_id = params.get("pid") or params.get("project_id")
    image_id = params.get("image_id")
    doc_id = params.get("docId") or params.get("doc_id")
    version_id = params.get("versionId") or params.get("version_id")
    page_id = params.get("pageId") or params.get("page_id")
    sid = params.get("sid") or params.get("short_id")

    combined_route = f"{path}/{fragment_path}".lower()

    if sid or "invite" in combined_route or "share" in combined_route:
        url_type = "invite_link"
    elif doc_id or "product" in combined_route:
        url_type = "product_doc"
    elif image_id or "detaildetach" in combined_route:
        url_type = "screen_detail"
    elif project_id or "stage" in combined_route:
        url_type = "stage_project"
    else:
        url_type = "unknown"

    return LanhuParsedURL(
        raw_url=raw_url,
        url_type=url_type,
        project_id=project_id,
        team_id=team_id,
        image_id=image_id,
        doc_id=doc_id,
        version_id=version_id,
        page_id=page_id,
        sid=sid,
    )

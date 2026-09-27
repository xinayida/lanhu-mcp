import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from lanhu_mcp.client import LanhuClient
from lanhu_mcp.models import LanhuAsset


@pytest.mark.asyncio
async def test_batch_download_assets_generates_manifest(tmp_path: Path):
    client = LanhuClient(auth=MagicMock())

    # Mock download_asset 方法
    async def mock_download(asset: LanhuAsset, save_dir: str | None = None) -> str:
        target_file = Path(save_dir) / f"{asset.name}.{asset.format}"
        target_file.write_text("dummy-content", encoding="utf-8")
        return str(target_file)

    client.download_asset = mock_download

    assets = [
        LanhuAsset(id="a1", name="icon_arrow_left", format="svg", width=24, height=24, download_url="http://example.com/1"),
        LanhuAsset(id="a2", name="banner_bg", format="webp", width=375, height=200, download_url="http://example.com/2"),
    ]

    export_res = await client.batch_download_assets(assets, save_dir=str(tmp_path))

    assert export_res["total_count"] == 2
    assert export_res["success_count"] == 2
    assert len(export_res["assets"]) == 2

    # 检查返回的属性
    a1_res = export_res["assets"][0]
    assert a1_res["name"] == "icon_arrow_left"
    assert a1_res["format"] == "svg"
    assert "IconArrowLeft" in a1_res["import_statement"]

    # 检查目标目录生成的 manifest.json
    manifest_file = tmp_path / "manifest.json"
    assert manifest_file.exists()

    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["total_count"] == 2
    assert data["success_count"] == 2

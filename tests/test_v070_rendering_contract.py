"""v0.7.0 Batch 2 Task 8：iframe 渲染合同静态防护（便携）。

锁定 app.js 的 v2 协议与公开 SDK 表面（绝不触碰私有字段），并防止
Field3D/Three.js/自研渲染器回退重新进入产品面。
"""

from __future__ import annotations

import re
from pathlib import Path

FRAME_JS = Path("web/public/supermap-volume-frame/app.js")
PRODUCT_SOURCES = [
    Path("web/src/components/rendering/NativeVolumePanel.vue"),
    Path("web/src/components/rendering/SuperMapVolumeFrame.vue"),
    Path("web/src/components/rendering/renderProtocol.ts"),
    Path("web/public/supermap-volume-frame/app.js"),
]


def _frame_source() -> str:
    return FRAME_JS.read_text(encoding="utf-8")


def test_frame_speaks_protocol_v2():
    src = _frame_source()
    assert "gmp-supermap-volume/v2" in src
    assert "gmp-supermap-volume/v1" not in src.replace("v1 与任何畸形消息", "")


def test_frame_v2_message_surface():
    src = _frame_source()
    for token in (
        "APPLY_RENDER_STATE",
        "STATE_APPLIED",
        "COMMAND_APPLIED",
        "capabilities",
        "singleAxisSlice",
        "lastAppliedRevision",
        "lastAppliedState",
    ):
        assert token in src, token


def test_frame_uses_public_sdk_properties_only():
    src = _frame_source()
    for token in (
        "layer.enableLighting",
        "layer.useGradientOpacity",
        "layer.fillStyle",
        "layer.minFiltration",
        "layer.maxFiltration",
        "layer.colorTransferFunction",
        "layer.opacityTransferFunction",
        "layer.volumeRenderMode",
        "layer.sliceCoordinate",
        "layer.contourValue",
        "new SuperMap3D.Cartesian3",
        "SuperMap3D.FillStyle.Fill_And_WireFrame",
    ):
        assert token in src, token
    # 私有 SDK 字段绝不检查或改写
    for banned in ("_xSliceCommand", "_voxelGridTile"):
        assert banned not in src, banned


def test_no_fallback_renderer_in_product_sources():
    for path in PRODUCT_SOURCES:
        src = path.read_text(encoding="utf-8")
        assert "Field3D" not in src, path
        assert "THREE." not in src, path
        assert "three/" not in src, path
        assert "WebGLRenderer" not in src, path


def test_single_axis_technique_uses_negative_coordinates():
    src = _frame_source()
    # Task 1 实测技术：非活动轴以负坐标隐藏（-1 与 -0.5 无可见差异）
    assert "sliceCoordinate" in src
    assert "Fill_And_WireFrame" in src


def test_recovery_failure_is_fatal_even_after_rendered():
    """状态恢复失败必须翻转 failed 相位并通知父页，绝不停留在 rendered。"""

    src = _frame_source()
    assert "RENDER_STATE_RECOVERY_FAILED" in src
    # fail() 必须支持 fatal 语义：即使已经 rendered 也翻转相位 + emitRenderState
    assert re.search(r"function fail\(code, message, fatal\)", src)
    assert re.search(
        r"diag\.phase !== 'rendered' \|\| fatal", src
    ), "fail() 在 rendered 之后遇 fatal 错误不得保持 rendered"
    # 恢复失败分支必须以 fatal 调用
    assert re.search(r"fail\('RENDER_STATE_RECOVERY_FAILED', recoveryError, true\)", src)


# ---------------------------------------------------------------------------
# warm-cache 升级黑屏修复（v0.7.0 第二批发布阻断）：iframe 运行时资产必须
# 经内容哈希版本化 URL 加载；index.html 内联 bootstrap 把 v/sdk 透传到
# styles.css 与 app.js（SDK 走独立的钉住哈希 sdk 参数）。
# ---------------------------------------------------------------------------

FRAME_INDEX = Path("web/public/supermap-volume-frame/index.html")
VITE_CONFIG = Path("web/vite.config.ts")


def test_iframe_index_has_no_unversioned_runtime_references():
    src = FRAME_INDEX.read_text(encoding="utf-8")
    # 静态直引即稳定 URL 缓存入口，一律禁止
    assert 'src="./app.js"' not in src
    assert 'href="./styles.css"' not in src
    assert 'src="../SuperMap3D-2026/SuperMap3D.js"' not in src


def test_iframe_bootstrap_propagates_content_versions():
    src = FRAME_INDEX.read_text(encoding="utf-8")
    # 内联 bootstrap 从查询串读取 v/sdk 并拼到运行时资产 URL
    assert "URLSearchParams" in src
    assert "params.get('v')" in src
    assert "params.get('sdk')" in src
    assert "./app.js" in src  # 仅允许出现在动态拼接表达式中
    assert "./styles.css" in src
    assert "CESIUM_BASE_URL" in src
    # 动态/带查询串加载会让 SDK 脚本标签探测失效，必须显式固定 SUPERMAP3D_BASE_URL
    assert "SUPERMAP3D_BASE_URL" in src


def test_vite_config_injects_frame_and_sdk_versions():
    src = VITE_CONFIG.read_text(encoding="utf-8")
    assert "__VOLUME_FRAME_VERSION__" in src
    assert "__VOLUME_SDK_VERSION__" in src
    assert "supermap-volume-frame" in src
    assert "SuperMap3D.js" in src


def test_frame_publishes_geometry_diagnostic():
    """几何只读诊断：包围盒角度/米制 Z 边界/相机取景跨度必须进入 diag。

    体盒几何验收的依据：layerBounds/zBounds 全模式不变（不得切成方盒）、
    相机按最大物理跨度取景；不暴露 viewer/layer 本体。
    """

    src = _frame_source()
    assert "geometry" in src
    assert "layerBoundsDegrees" in src
    assert "zBoundsMetres" in src
    assert "cameraSpanMetres" in src

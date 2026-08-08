"""v0.8.0 Task 9: CI contract — resistivity scattered / DSI-like browser specs.

在 v0.5/v0.6 CI 合同（``tests/test_v05_ci_contract.py`` /
``tests/test_v06_ci_contract.py``）之上锁定 v0.8.0 浏览器验收增量：

- Mock E2E 新增 ``web/e2e/resistivity-scattered.spec.ts``：预置卡 → 统一工作台
  → DSI-like 实验（免责声明）→ 成功候选 → 成果页渲染链的关键锚点一个不少；
- Live E2E 新增 ``web/e2e-live/resistivity-scattered-live.spec.ts``：隔离运行时
  + ``GEOMODELING_RHO_SOURCE`` 跳过门（CI browser-live 无私有源，必须干净
  跳过并输出原因），渲染门复用 v070RenderGates 判据；
- 旧 legacy 电阻率产品页门 ``web/e2e-live/legacy-volume-live.spec.ts`` 随入口
  410 退役删除，不得复活（退役行为由便携测试
  ``tests/test_rendering_api.py`` / ``tests/test_case_workspace_api.py`` 锁定）；
- Mock 层的旧导入用例（``web/e2e/supermap-native-volume.spec.ts``）改写为
  410 退役合同断言；
- warm-cache 四缓存场景门（``web/e2e-live/warm-cache-upgrade-live.spec.ts``）
  迁移到电阻率散点预置 candidate_result 链（GEOMODELING_RHO_SOURCE 跳过门
  先于 describe；legacyGrid 合成网格夹具随唯一消费者迁移删除）；
- browser-live CI 过滤口径不变（仅 platform-live.spec.ts），CI 不引入私有源
  环境变量——新 live 规格只作本机发布门；
- 证据目录骨架 ``docs/evidence/v0.8.0-resistivity-dsi-like/README.md`` 存在且
  只含生成约定（结果由真实运行单独提交）。

v0.8.0 第二批 Task 9 增量（统计与空间分析中心）：

- Live E2E 新增 ``web/e2e-live/analysis-center-live.spec.ts``：微震/电阻率
  双预置 seed + ``GEOMODELING_RHO_SOURCE`` 文件级跳过门（声明先于
  describe）+ analysis-summary API 合同门 + 桌面/移动视觉门 + 空间分箱/
  剖面轴/模型对比交互门；只作本机发布门，不进 CI browser-live 过滤；
- 证据目录骨架 ``docs/evidence/v0.8.0-statistics-analysis/README.md`` 存在
  且只含生成约定；一旦真实证据入库，run 目录身份 JSON 的 git_commit 必须
  是当前 HEAD 的祖先（与电阻率证据同一祖先检查，共享同一辅助函数）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(".github/workflows/ci.yml")
MOCK_SPEC = Path("web/e2e/resistivity-scattered.spec.ts")
LIVE_SPEC = Path("web/e2e-live/resistivity-scattered-live.spec.ts")
RETIRED_LIVE_SPEC = Path("web/e2e-live/legacy-volume-live.spec.ts")
MOCK_VOLUME_SPEC = Path("web/e2e/supermap-native-volume.spec.ts")
EVIDENCE_README = Path("docs/evidence/v0.8.0-resistivity-dsi-like/README.md")
WARM_CACHE_LIVE_SPEC = Path("web/e2e-live/warm-cache-upgrade-live.spec.ts")
LEGACY_GRID_FIXTURE = Path("web/e2e-live/fixtures/legacyGrid.ts")
ANALYSIS_LIVE_SPEC = Path("web/e2e-live/analysis-center-live.spec.ts")
ANALYSIS_EVIDENCE_README = Path("docs/evidence/v0.8.0-statistics-analysis/README.md")

MOCK_SPEC_MARKERS = (
    # 预置卡身份（无旧语样断言）
    "标准化散点 · 17,549 个节点",
    "散点预置 · 官方普通克里金成果",
    # 统一工作台
    "case-workspace-header",
    "workspace-data",
    "open-official-result",
    "new-experiment",
    # DSI-like 实验：算法标签 + 免责声明 + 固定合同
    "algo-dsi-like",
    "DSI-like 离散平滑插值",
    "不等同于 GOCAD DSI",
    "dsi-hard-constraints",
    # 成功候选 → 成果页渲染链
    "candidate-row",
    "dsi_like",
    "volume-phase",
    "axis-x",
    "axis-y",
    "axis-z",
    "slice-analysis",
    "export-slice",
)

LIVE_SPEC_MARKERS = (
    # 跳过门与隔离运行时
    "GEOMODELING_RHO_SOURCE",
    "test.skip",
    "GEOMODELING_DATA_DIR",
    "seed-resistivity",
    # 退役确认与身份链
    "LEGACY_RESISTIVITY_RETIRED",
    "builtin_preset",
    "candidate_result",
    # DSI-like 产品链与渲染门
    "algo-dsi-like",
    "不等同于 GOCAD DSI",
    "dsi_like",
    "runV070RenderGates",
    "--use-angle=gl",
    # 普通刷新场景与证据目录
    "page.reload",
    "docs/evidence/v0.8.0-resistivity-dsi-like",
)

WARM_CACHE_SPEC_MARKERS = (
    # 跳过门与预置 seed
    "GEOMODELING_RHO_SOURCE",
    "test.skip",
    "seed-resistivity",
    # candidate_result 身份链（工作台 → 官方成果 → 显式 POST 资产）
    "candidate_result",
    "/api/cases/resistivity/workspace",
    "/api/results/",
    "render-assets/netcdf",
    # 端口环境变量与实测可 bind 默认值（Hyper-V 保留段 5141–5240 之外）
    "GEOMODELING_WARM_CACHE_PORT",
    "5278",
    # 证据目录
    "docs/evidence/v0.8.0-resistivity-dsi-like",
)

ANALYSIS_LIVE_SPEC_MARKERS = (
    # 跳过门与隔离运行时（文件级 test.skip 先于 describe）
    "GEOMODELING_RHO_SOURCE",
    "test.skip",
    "GEOMODELING_DATA_DIR",
    # 双预置 seed（微震只读预置 + 电阻率外部私有源）
    "seed-microseismic",
    "seed-resistivity",
    # analysis-summary API 合同门
    "analysis-summary",
    "analysis_profile",
    "microseismic_velocity",
    "17_549",
    "1_911",
    "source_sha256",
    # 桌面/移动视觉门与交互门
    "analysis-profile-badge",
    "analysis-quality-badge",
    "spatial-anomaly-legend",
    "spatial-chart",
    "model-candidate-row",
    "axis=xy",
    "1440",
    "390",
    "--use-angle=gl",
    # 证据目录
    "docs/evidence/v0.8.0-statistics-analysis",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"{path} 不存在"
    return path.read_text(encoding="utf-8")


def test_mock_e2e_spec_covers_resistivity_dsi_like_flow():
    text = _read(MOCK_SPEC)
    missing = [marker for marker in MOCK_SPEC_MARKERS if marker not in text]
    assert not missing, f"Mock E2E 规格缺少电阻率散点/DSI-like 链路锚点：{missing}"


def test_live_spec_has_source_skip_gate_isolation_and_render_gates():
    text = _read(LIVE_SPEC)
    missing = [marker for marker in LIVE_SPEC_MARKERS if marker not in text]
    assert not missing, f"Live 规格缺少跳过门/隔离/渲染门锚点：{missing}"
    # 跳过门必须在任何测试声明之前生效（文件级 test.skip）
    assert text.index("test.skip(") < text.index("test.describe("), (
        "GEOMODELING_RHO_SOURCE 跳过门必须先于 test.describe 声明"
    )


def test_live_retirement_evidence_serializes_numeric_statuses():
    text = _read(LIVE_SPEC)
    assert "retiredChecks[`${method} ${p}`] = resp.status()" in text, (
        "退役证据必须保存 HTTP 状态码数值；保存 status 函数会在 JSON 序列化时丢失"
    )


def test_legacy_volume_live_spec_is_retired():
    assert not RETIRED_LIVE_SPEC.exists(), (
        "旧 legacy 电阻率产品页门已随入口 410 退役删除，不得复活"
    )


def test_warm_cache_live_spec_uses_resistivity_preset_candidate_chain():
    text = _read(WARM_CACHE_LIVE_SPEC)
    missing = [marker for marker in WARM_CACHE_SPEC_MARKERS if marker not in text]
    assert not missing, f"warm-cache live 规格缺少预置/candidate 链锚点：{missing}"
    # 跳过门必须在任何测试声明之前生效（文件级 test.skip）
    assert text.index("test.skip(") < text.index("test.describe("), (
        "GEOMODELING_RHO_SOURCE 跳过门必须先于 test.describe 声明"
    )
    # 已 410 退役的 legacy 链不得回流（CLI 登记/合成网格夹具/legacy 资产路由）
    assert "render_cli" not in text
    assert "legacyGrid" not in text
    assert "syntheticLegacyGridCsv" not in text
    assert "/api/cases/resistivity/render-assets" not in text


def test_legacy_grid_fixture_removed_with_last_consumer():
    assert not LEGACY_GRID_FIXTURE.exists(), (
        "legacyGrid 合成网格夹具的唯一消费者已迁移到预置 candidate 链，"
        "文件必须删除，不得遗留死夹具"
    )


def test_mock_volume_spec_legacy_case_rewritten_to_retirement_contract():
    text = _read(MOCK_VOLUME_SPEC)
    assert "LEGACY_RESISTIVITY_RETIRED" in text, (
        "mock 层旧导入用例必须改写为 410 退役合同断言"
    )
    # 旧导入交互锚点（提交按钮/文件输入）不得再作为流程驱动出现
    assert "legacy-import-submit" not in text
    assert "legacy-import-file" not in text


def test_browser_live_ci_filter_unchanged_and_free_of_private_source():
    doc = yaml.safe_load(_read(CI))
    steps = [
        str(step.get("run", "") or step.get("uses", ""))
        for step in doc["jobs"]["browser-live"]["steps"]
    ]
    assert any("e2e-live/platform-live.spec.ts" in step for step in steps), (
        "browser-live 必须保持仅过滤 platform-live.spec.ts"
    )
    whole = _read(CI)
    assert "GEOMODELING_RHO_SOURCE" not in whole, (
        "CI 不得引入私有电阻率源环境变量；live 规格的跳过门是唯一机制"
    )
    assert "resistivity-scattered-live" not in whole, (
        "新 live 规格只作本机发布门，不得进入 CI browser-live 过滤"
    )


def _assert_committed_runs_have_ancestor_identity(evidence_dir: Path) -> None:
    """以 Git 跟踪口径判定（git ls-files）：本机未提交输出不算入库。骨架阶段

    不得预登记任何 run-* 结果；一旦真实证据入库，每个 run 目录必须携带
    记录 git_commit 的身份 JSON，且该提交必须是当前 HEAD 的祖先（或 HEAD
    本身）——证据与代码身份一致，不得用外来/未来提交冒充。
    """

    import json
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "--", str(evidence_dir)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    run_dirs = sorted(
        {
            "/".join(entry.split("/")[:-1])
            for entry in tracked.splitlines()
            if any(part.startswith("run-") for part in entry.split("/"))
        }
    )
    for run_dir in run_dirs:
        base = Path(run_dir)
        identity = base / "identity.json"
        scenarios = base / "scenarios.json"
        assert identity.is_file() or scenarios.is_file(), (
            f"入库证据缺少身份文件（identity.json/scenarios.json）：{run_dir}"
        )
        payload = json.loads((identity if identity.is_file() else scenarios).read_text("utf-8"))
        commit = payload.get("git_commit", "")
        assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), (
            f"证据 git_commit 非法：{run_dir}"
        )
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            check=False,
        ).returncode
        assert ancestor == 0, f"证据 git_commit 不是 HEAD 祖先：{run_dir} → {commit}"


def test_evidence_readme_skeleton_and_committed_runs_identity():
    text = _read(EVIDENCE_README)
    for marker in ("GEOMODELING_RHO_SOURCE", "seed-resistivity", "run_id", "git_commit"):
        assert marker in text, f"证据 README 缺少约定锚点：{marker}"
    _assert_committed_runs_have_ancestor_identity(EVIDENCE_README.parent)


def test_analysis_center_live_spec_has_dual_seed_skip_gate_and_visual_gates():
    text = _read(ANALYSIS_LIVE_SPEC)
    missing = [marker for marker in ANALYSIS_LIVE_SPEC_MARKERS if marker not in text]
    assert not missing, f"分析中心 live 规格缺少双 seed/跳过门/视觉门锚点：{missing}"
    # 跳过门必须在任何测试声明之前生效（文件级 test.skip）
    assert text.index("test.skip(") < text.index("test.describe("), (
        "GEOMODELING_RHO_SOURCE 跳过门必须先于 test.describe 声明"
    )
    # 与电阻率 live 同一纪律：新 live 规格只作本机发布门，不进 CI browser-live
    whole = _read(CI)
    assert "analysis-center-live" not in whole, (
        "分析中心 live 规格只作本机发布门，不得进入 CI browser-live 过滤"
    )


def test_analysis_evidence_readme_skeleton_and_committed_runs_identity():
    text = _read(ANALYSIS_EVIDENCE_README)
    for marker in (
        "GEOMODELING_RHO_SOURCE",
        "seed-resistivity",
        "seed-microseismic",
        "run_id",
        "git_commit",
    ):
        assert marker in text, f"分析证据 README 缺少约定锚点：{marker}"
    _assert_committed_runs_have_ancestor_identity(ANALYSIS_EVIDENCE_README.parent)

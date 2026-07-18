from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import write_json
from .schemas import (
    DatasetRegistration,
    MetricSummary,
    ModelMetadata,
    ModelSelection,
    ModelStatus,
    ModelTask,
    ResultInventoryItem,
    SuperMapResultRegistration,
    ValidationIssue,
    ViewConfiguration,
)


def _enum_value(value):
    return getattr(value, "value", value)


def model_metadata_from_config(
    model: dict[str, Any],
    input_dataset_id: str,
    input_sha256: str,
    supermap_result: SuperMapResultRegistration | None = None,
) -> ModelMetadata:
    grid: dict[str, Any] = {
        "resolution_xy_m": model.get("resolution_xy_m"),
        "nodata": -9999,
    }
    if supermap_result is not None:
        grid.update(
            {
                "rows": supermap_result.rows,
                "columns": supermap_result.columns,
                "bands": supermap_result.bands,
            }
        )
    succeeded = supermap_result is not None and _enum_value(supermap_result.status) == ModelStatus.SUCCEEDED.value
    return ModelMetadata(
        model_id=model["model_id"],
        property="RHO",
        property_unit=None,
        method=model["method"],
        input_dataset_id=input_dataset_id,
        input_sha256=input_sha256,
        crs={"type": "local_engineering", "epsg": None},
        axis={"horizontal_unit": "m", "vertical_unit": "m", "z_positive": "up"},
        grid=grid,
        parameters=model.get("parameters", {}) | {"neighbor_count": model.get("neighbor_count"), "role": model.get("role")},
        supermap={} if supermap_result is None else supermap_result.model_dump(mode="json"),
        status=ModelStatus.SUCCEEDED if succeeded else ModelStatus.CREATED,
    )


def export_model_metadata(metadata: ModelMetadata, path: str | Path) -> Path:
    return write_json(path, metadata)


def export_model_markdown(metadata: ModelMetadata, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 模型元数据：{metadata.model_id}",
        "",
        f"- 属性：{metadata.property}",
        f"- 属性单位：{metadata.property_unit or '待来源确认'}",
        f"- 方法：{metadata.method}",
        f"- 输入数据集：{metadata.input_dataset_id}",
        f"- 输入 SHA-256：`{metadata.input_sha256}`",
        f"- 状态：{metadata.status}",
        f"- CRS：{metadata.crs}",
        f"- 轴：{metadata.axis}",
        f"- 网格：{metadata.grid}",
        f"- 参数：{metadata.parameters}",
        "",
        "## 说明",
        "",
        "- IDW 和普通克里金不得登记为 DSI。",
        "- SuperMap 内部数据集仅在真实受支持 API 检查成功后才能标记为 dataset_verified。",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_metrics_json(summaries: dict[str, MetricSummary], comparison: dict[str, Any], path: str | Path) -> Path:
    return write_json(path, {"summaries": {name: summary.model_dump(mode="json") for name, summary in summaries.items()}, "baseline_comparison": comparison})


def export_metrics_markdown(summaries: dict[str, MetricSummary], comparison: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 电阻率模型验证指标复算报告",
        "",
        "| 模型 | 总数 | 有效点 | NoData | 覆盖率 | MAE | RMSE | R² | Bias | P90 AE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, summary in summaries.items():
        lines.append(
            f"| {name} | {summary.n_total} | {summary.n_valid} | {summary.n_nodata} | {summary.coverage_rate:.6f} | {summary.mae:.6f} | {summary.rmse:.6f} | {summary.r2:.6f} | {summary.bias:.6f} | {summary.p90_abs_error:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 基线比较",
            "",
            f"- 与总体指标基线一致：{comparison['passed']}",
            f"- 检查模型数：{comparison['models_checked']}",
            "",
            "## 选型结论",
            "",
            "- 默认展示模型：`Kriging 20m/40点`，其 MAE、中位绝对误差和平均相对误差最优。",
            "- 正式对照模型：`IDW 20m/25点`，其 RMSE、R² 和 log10 RMSE 更优。",
            "- 不生成任一模型“全面最优”的结论。",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_inventory_json(items: list[ResultInventoryItem], path: str | Path) -> Path:
    return write_json(path, [item.model_dump(mode="json") for item in items])


def export_inventory_markdown(items: list[ResultInventoryItem], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SuperMap 成果清单",
        "",
        "| 名称 | 类别 | 状态 | 证据等级 | SuperMap 数据集 | 路径 |",
        "|---|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(f"| {item.name} | {item.category} | {item.status} | {item.evidence_level} | {item.supermap_dataset or ''} | {item.path or ''} |")
    lines.extend(
        [
            "",
            "## 完整性规则",
            "",
            "- 空结果、失败任务或不可打开输出不得进入正式成果。",
            "- `RHO_ISO_77_K40` 与 `RHO_ISO_HIGH_P95_K40` 当前仅作为失败/空结果证据登记。",
            "- declared 或 manual_evidence 不得表述为程序化数据集验证。",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_dataset_markdown(registrations: list[DatasetRegistration], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 数据集清单", "", "| dataset_id | 类型 | 行数 | 质量状态 | SHA-256 |", "|---|---|---:|---|---|"]
    for item in registrations:
        lines.append(f"| {item.dataset_id} | {item.dataset_type} | {item.row_count} | {item.quality_status} | `{item.sha256}` |")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_model_list_markdown(tasks: list[ModelTask], selection: ModelSelection | None, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 模型任务清单", "", "| model_id | 名称 | 方法 | 角色 | 状态 | 输入数据集 |", "|---|---|---|---|---|---|"]
    for task in tasks:
        lines.append(f"| {task.model_id} | {task.display_name} | {task.method} | {task.role} | {task.status} | {task.input_dataset_id} |")
    if selection is not None:
        lines.extend(["", "## 默认/对照选择", "", f"- 默认模型：`{selection.default_model_id}`", f"- 对照模型：`{selection.comparison_model_id}`", f"- 依据：{selection.rationale}"])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_issues_json(issues: list[ValidationIssue], path: str | Path) -> Path:
    return write_json(path, [issue.model_dump(mode="json") for issue in issues])


def export_issues_markdown(issues: list[ValidationIssue], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 问题清单", "", "| 严重级别 | 代码 | 影响范围 | 阻断正式成果 | 当前处理 |", "|---|---|---|---|---|"]
    for issue in issues:
        lines.append(f"| {issue.severity} | {issue.code} | {issue.scope or ''} | {issue.blocking} | {issue.current_handling or ''} |")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_view_configurations_json(views: list[ViewConfiguration], path: str | Path) -> Path:
    return write_json(path, [view.model_dump(mode="json") for view in views])


def export_view_configurations_markdown(views: list[ViewConfiguration], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 三维成果与视图配置", "", "| 名称 | 数据集 | 证据等级 | 行×列×波段 | 数值范围 | 垂直切片 | 等值面 |", "|---|---|---|---|---|---|---|"]
    for view in views:
        dims = f"{view.rows}×{view.columns}×{view.bands}"
        value_range = f"{view.value_min}—{view.value_max}"
        lines.append(f"| {view.name} | {view.dataset} | {view.evidence_level} | {dims} | {value_range} | {view.vertical_slice_status} | {view.isosurface_status} |")
    lines.extend(["", "## 阈值说明", "", "- `RHO >= 77` 仅为工程演示阈值，不得称为已论证地质危险阈值。"])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def export_acceptance_summary(
    path: str | Path,
    datasets: list[DatasetRegistration],
    tasks: list[ModelTask],
    selection: ModelSelection | None,
    summaries: dict[str, MetricSummary],
    comparison: dict[str, Any],
    records: list[SuperMapResultRegistration],
    views: list[ViewConfiguration],
    issues: list[ValidationIssue],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    formal = [record for record in records if _enum_value(record.result_category) == "formal" and _enum_value(record.status) == "succeeded"]
    file_verified = [record for record in records if record.file_verified]
    dataset_verified = [record for record in records if record.dataset_verified]
    lines = [
        "# v0.1 验收摘要",
        "",
        "## 已验证",
        "",
        f"- 数据集登记与契约校验：{len(datasets)} 个数据集。",
        f"- 模型任务：{len(tasks)} 个任务；默认/对照选择：{selection.default_model_id if selection else '未导出'} / {selection.comparison_model_id if selection else '未导出'}。",
        f"- 指标复算：{len(summaries)} 个模型；总体指标基线比较 passed={comparison['passed']}。",
        f"- SuperMap 文件级验证：{len(file_verified)} 个配置成果关联到存在的 UDBX 文件。",
        "",
        "## 证据边界",
        "",
        f"- SuperMap dataset_verified 数量：{len(dataset_verified)}；当前不声称程序化数据集级验证。",
        f"- 正式配置成果：{len(formal)} 个；失败/空等值面不进入正式成果。",
        f"- 视图配置：{len(views)} 项；完整体元和水平切片为 manual_evidence，垂直切片为 unverified，等值面为 failed。",
        f"- 问题清单：{len(issues)} 项，包含 RHO 单位、CRS/EPSG、垂直切片、等值面和 SuperMap 数据集级验证边界。",
        "",
        "## 未实现",
        "",
        "- 微震三维坐标重建、瓦斯三维融合、DSI-like 插值内核、Web 前端、用户系统、云部署和 iServer 发布均未实现。",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output

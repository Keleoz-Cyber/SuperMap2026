from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import write_json
from .schemas import MetricSummary, ModelMetadata, ModelStatus, ResultInventoryItem, SuperMapResultRegistration


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
        status=ModelStatus.SUCCEEDED if supermap_result is not None and supermap_result.status == ModelStatus.SUCCEEDED else ModelStatus.CREATED,
    )


def export_model_metadata(metadata: ModelMetadata, path: str | Path) -> Path:
    return write_json(path, metadata)


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
        "| 名称 | 类别 | 状态 | SuperMap 数据集 | 路径 |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(f"| {item.name} | {item.category} | {item.status} | {item.supermap_dataset or ''} | {item.path or ''} |")
    lines.extend(
        [
            "",
            "## 完整性规则",
            "",
            "- 空结果、失败任务或不可打开输出不得进入正式成果。",
            "- `RHO_ISO_77_K40` 与 `RHO_ISO_HIGH_P95_K40` 当前仅作为失败/空结果证据登记。",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output

"""DSI-like 离散平滑插值（仅 3D）：网格趋势场 + 原始观测点残差精确化两层结构。

**定位声明**：本平台 "DSI-like" 是借鉴离散平滑插值思想的 Python 工程近似，
**不等同 GOCAD DSI**，也不宣称给出唯一真实地质结构。算法无随机种子，相同
输入产生相同预测字节。

计算流程（设计 §4.2）：

1. **工作网格推导**：``fit`` 用 ``modeling.grid.derive_grid(points, "3d", None)``
   的默认口径（``_default_grid``：观测三维包围盒 + 二分尺度使节点数不超过
   ``DEFAULT_CELL_TARGET = 100_000`` 的 max-cells 预算，轴节点规则见
   ``_axis_nodes``）派生内部规则网格；维度顺序固定 ``(x, y, z)``，
   ``meshgrid(indexing="ij")`` 按 C 顺序展开，节点坐标完全确定。插值器永远
   拿不到实验网格合同，逐折/物化两条调用路径共用同一推导口径。
2. **观测→节点映射（只影响趋势层）**：每个观测逐轴吸附到最近节点
   （``ceil(frac - 0.5)``，并列取较低下标；退化轴固定下标 0）。同一节点
   被多个观测命中时取均值（碰撞规则）。**吸附与碰撞均值只作用于网格趋势
   场**；原始观测点的精确性不由吸附保证，而由第 6 步的残差层在原始坐标
   上保证（见下）。
3. **初始场**：现有 ``IDWInterpolator``（``power=init_power``、
   ``min_neighbors=3``）在训练点上拟合，对全部工作网格节点预测；落在观测
   包围盒外或初始值非有限的节点为不受支持节点，恒为 NoData、永不更新。
4. **平滑**：加权 Jacobi——``v ← v + smoothing_strength · (有效邻居均值 − v)``，
   只更新受支持且非观测的节点；有效邻居是 6/18/26 连通中落在网格内且非
   NoData 的节点（各方向等权），零有效邻居节点保持初值。每轮结束后把观测
   节点写回观测值（趋势层内观测节点恒锁定）。每轮检查 ``cancel()``，取消
   时按 IDW 的取消模式抛 ``RUN_CANCELED``。
5. **停止门**：迭代达 ``max_iterations`` 或本轮最大 |Δ| <
   ``convergence_tolerance``。**达到 max_iterations 未收敛不是失败**——这是
   有界工程近似（设计 §4.2 第 5 条允许两种停止），diagnostics 报
   ``converged=False``，候选仍可成功、可物化。
6. **残差精确化层（原始观测点硬约束）**：平滑结束后，在**原始训练点坐
   标**上复算趋势场三线性值，得残差 ``r_i = v_i − 三线性(趋势场, p_i)``；
   用现有 ``IDWInterpolator``（``power=init_power``、``min_neighbors=1``，
   IDW 在数据点处精确复现）对残差建模。最终
   ``predict(query) = 三线性(趋势, query) + IDW_残差(query)``。
   观测包围盒外仍恒 NoData——残差层只在趋势层有值处叠加修正，绝不把值
   带出盒外。
7. **观测点输出门**：全部训练点复算误差 ``max |predict(p_i) − v_i|`` 必须
   ≤ ``1e-8``，否则 ``DSI_LIKE_CONSTRAINT_VIOLATION`` fail-closed；
   diagnostics 记录 ``max_observation_error``。

**网格采样合同**：``predict`` 对平滑趋势场做三线性采样并叠加残差修正；
查询点落在观测包围盒外 → ``is_nodata=True``；三线性角点含 NoData →
NoData（不外推、不编造）。恰在原始训练坐标上的查询返回观测原值（残差层
精确化），留出点（不在约束集合）走一般插值，不被精确复现。

失败语义（全部 fail-closed，带稳定码的 ``PlatformError``）：

- ``DSI_LIKE_INPUT_INVALID``：形状/维度不符、坐标与值数量不一致、空输入、
  非有限坐标或值；
- ``DSI_LIKE_DUPLICATE_COORDINATES``：重复训练坐标；
- ``DSI_LIKE_NO_SUPPORTED_NODES``：受支持节点数为 0（训练点不足以让 3 邻居
  IDW 初始化产生任何有效节点，如点数 < 3 或工作网格退化）；
- ``DSI_LIKE_NON_FINITE_FIELD``：迭代中出现非有限值；
- ``DSI_LIKE_OUTPUT_GATE_VIOLATION``：趋势场输出门（受支持节点有限性 +
  观测节点值保真，设计 §4.2 第 6 条）违例；
- ``DSI_LIKE_CONSTRAINT_VIOLATION``：训练点复算误差超 ``1e-8``（含复算
  出现 NoData/非有限），原始观测点硬约束不成立；
- ``RUN_CANCELED``：协作式取消（与 IDW 同码、同 http_status=409）。

diagnostics（有界）：``iterations``、``converged``、``max_delta``、
``supported_count``、``grid_shape``、``max_observation_error``
（predict 另附 ``n_targets``）。``auxiliary`` 恒为空字典（无原生不确定性）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import Field

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.grid import derive_grid
from geomodeling.modeling.idw import IDWInterpolator, IDWParameters, _IDWFitted
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm, ContractModel, Dimension

PREDICTION_CHUNK_SIZE = 20_000
RUN_CANCELED = "RUN_CANCELED"
DSI_LIKE_INPUT_INVALID = "DSI_LIKE_INPUT_INVALID"
DSI_LIKE_DUPLICATE_COORDINATES = "DSI_LIKE_DUPLICATE_COORDINATES"
DSI_LIKE_NO_SUPPORTED_NODES = "DSI_LIKE_NO_SUPPORTED_NODES"
DSI_LIKE_NON_FINITE_FIELD = "DSI_LIKE_NON_FINITE_FIELD"
DSI_LIKE_OUTPUT_GATE_VIOLATION = "DSI_LIKE_OUTPUT_GATE_VIOLATION"
DSI_LIKE_CONSTRAINT_VIOLATION = "DSI_LIKE_CONSTRAINT_VIOLATION"

# IDW 初始化的最少邻居数：训练点不足时初始场全空 → 零受支持节点类型化失败
_INIT_MIN_NEIGHBORS = 3
# 趋势场输出门观测保真容差（观测节点每轮写回原值，正常路径恒满足）
_OBSERVED_GATE_TOLERANCE = 1e-9
# 原始观测点硬约束门：全部训练点复算误差上限（残差层精确化，正常 ~1e-14）
_CONSTRAINT_GATE_TOLERANCE = 1e-8


class DSIParameters(ContractModel):
    init_power: float = Field(default=2.0, gt=0, le=8)
    neighbor_connectivity: Literal[6, 18, 26] = 6
    smoothing_strength: float = Field(default=0.5, gt=0, le=1)
    max_iterations: Literal[25, 50] = 25
    convergence_tolerance: float = Field(default=1e-4, gt=0, le=1)
    hard_constraints: Literal[True] = True


def _neighbor_offsets(connectivity: int) -> tuple[tuple[int, int, int], ...]:
    """6=面邻接、18=面+棱、26=面+棱+角；不含自身，顺序固定（确定性）。"""

    offsets = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                nonzero = (dx != 0) + (dy != 0) + (dz != 0)
                if nonzero == 0:
                    continue
                if connectivity == 6 and nonzero != 1:
                    continue
                if connectivity == 18 and nonzero > 2:
                    continue
                offsets.append((dx, dy, dz))
    return tuple(offsets)


def _snap_to_nodes(points: np.ndarray, axes: tuple[np.ndarray, ...]) -> np.ndarray:
    """逐轴最近节点下标：``ceil(frac - 0.5)``，并列取较低下标；退化轴取 0。"""

    index = np.zeros((points.shape[0], len(axes)), dtype=np.int64)
    for dim, axis in enumerate(axes):
        if len(axis) > 1 and axis[-1] > axis[0]:
            step = (axis[-1] - axis[0]) / (len(axis) - 1)
            frac = (points[:, dim] - axis[0]) / step
            index[:, dim] = np.clip(np.ceil(frac - 0.5), 0, len(axis) - 1).astype(np.int64)
    return index


class DSILikeInterpolator:
    algorithm = Algorithm.DSI_LIKE

    def validate_parameters(
        self, parameters: dict[str, Any], dimension: Dimension | str
    ) -> DSIParameters:
        if Dimension(dimension) == Dimension.TWO_D:  # 维度合法性统一入口；dsi_like 仅 3d
            raise ValueError("dsi_like 仅支持三维（3d）散点数据，2d 不可用")
        return DSIParameters.model_validate(parameters or {})

    def fit(
        self,
        coordinates: np.ndarray,
        values: np.ndarray,
        parameters: DSIParameters,
        *,
        cancel: CancelFn | None = None,
    ) -> "_DSILikeFitted":
        cancel = cancel or (lambda: False)
        coordinates = np.asarray(coordinates, dtype="float64")
        values = np.asarray(values, dtype="float64")
        if coordinates.ndim != 2 or coordinates.shape[1] != 3:
            raise PlatformError(
                DSI_LIKE_INPUT_INVALID,
                "dsi_like 需要 (n, 3) 三维训练坐标",
                {"shape": list(coordinates.shape)},
            )
        if values.ndim != 1 or values.shape[0] != coordinates.shape[0]:
            raise PlatformError(
                DSI_LIKE_INPUT_INVALID,
                "训练坐标与属性数量不一致",
                {"coordinates": coordinates.shape[0], "values": values.size},
            )
        if coordinates.shape[0] == 0:
            raise PlatformError(DSI_LIKE_INPUT_INVALID, "训练点为空，无法建模", {})
        if not (np.isfinite(coordinates).all() and np.isfinite(values).all()):
            raise PlatformError(
                DSI_LIKE_INPUT_INVALID, "训练坐标或属性包含非有限值", {}
            )
        if np.unique(coordinates, axis=0).shape[0] != coordinates.shape[0]:
            raise PlatformError(
                DSI_LIKE_DUPLICATE_COORDINATES,
                "训练坐标存在重复",
                {"points": coordinates.shape[0]},
            )

        # 1. 工作网格：derive_grid 默认口径（观测包围盒 + DEFAULT_CELL_TARGET 预算）
        grid = derive_grid(coordinates, "3d", None)
        axes = tuple(np.asarray(axis, dtype="float64") for axis in grid.axes)
        shape = tuple(len(axis) for axis in axes)
        meshes = np.meshgrid(*axes, indexing="ij")
        nodes = np.column_stack([mesh.ravel() for mesh in meshes])

        # 2. 观测→节点吸附（同节点多观测取均值）
        obs_index = _snap_to_nodes(coordinates, axes)
        flat = (obs_index[:, 0] * shape[1] + obs_index[:, 1]) * shape[2] + obs_index[:, 2]
        sums = np.zeros(nodes.shape[0], dtype="float64")
        counts = np.zeros(nodes.shape[0], dtype="float64")
        np.add.at(sums, flat, values)
        np.add.at(counts, flat, 1.0)
        observed_flat = counts > 0
        observed_values_flat = np.where(
            observed_flat, sums / np.where(observed_flat, counts, 1.0), np.nan
        )

        # 3. IDW 初始场；包围盒外或初始值非有限的节点不受支持，恒为 NoData
        idw_fitted = IDWInterpolator().fit(
            coordinates,
            values,
            IDWParameters(power=parameters.init_power, min_neighbors=_INIT_MIN_NEIGHBORS),
        )
        initial = idw_fitted.predict(nodes, cancel=cancel)
        lows = coordinates.min(axis=0)
        highs = coordinates.max(axis=0)
        inside = np.all((nodes >= lows) & (nodes <= highs), axis=1).reshape(shape)
        field = initial.values.reshape(shape)
        supported = inside & np.isfinite(field)
        supported_count = int(supported.sum())
        if supported_count == 0:
            raise PlatformError(
                DSI_LIKE_NO_SUPPORTED_NODES,
                "工作网格受支持节点数为 0（训练点不足以建立 IDW 初始场）",
                {
                    "training_points": coordinates.shape[0],
                    "min_neighbors_required": _INIT_MIN_NEIGHBORS,
                },
            )
        field = np.where(supported, field, np.nan)
        observed = observed_flat.reshape(shape)
        observed_values = observed_values_flat.reshape(shape)
        # 硬约束：观测节点从初始场起即锁定为观测值
        field = np.where(observed, observed_values, field)

        # 4. 加权 Jacobi 平滑：只更新受支持且非观测的节点
        updatable = supported & ~observed
        offsets = _neighbor_offsets(parameters.neighbor_connectivity)
        iterations = 0
        converged = False
        max_delta = 0.0
        for iteration in range(1, parameters.max_iterations + 1):
            if cancel():
                raise PlatformError(
                    RUN_CANCELED, "任务已被取消", {"completed": iteration - 1}, http_status=409
                )
            padded = np.pad(field, 1, mode="constant", constant_values=np.nan)
            neighbor_sum = np.zeros(shape, dtype="float64")
            neighbor_count = np.zeros(shape, dtype="float64")
            for dx, dy, dz in offsets:
                window = padded[
                    1 + dx : 1 + dx + shape[0],
                    1 + dy : 1 + dy + shape[1],
                    1 + dz : 1 + dz + shape[2],
                ]
                valid = np.isfinite(window)
                neighbor_sum += np.where(valid, window, 0.0)
                neighbor_count += valid
            has_neighbors = neighbor_count > 0
            neighbor_mean = np.where(
                has_neighbors, neighbor_sum / np.where(has_neighbors, neighbor_count, 1.0), 0.0
            )
            targets = updatable & has_neighbors
            delta = np.where(
                targets, parameters.smoothing_strength * (neighbor_mean - field), 0.0
            )
            field = field + delta
            # 硬约束：每轮结束后观测节点写回原值
            field = np.where(observed, observed_values, field)
            if not np.isfinite(field[supported]).all():
                raise PlatformError(
                    DSI_LIKE_NON_FINITE_FIELD,
                    "DSI-like 平滑迭代出现非有限值",
                    {"iteration": iteration},
                )
            max_delta = float(np.abs(delta[targets]).max()) if targets.any() else 0.0
            iterations = iteration
            if max_delta < parameters.convergence_tolerance:
                converged = True
                break

        # 5. 趋势场输出门（设计 §4.2 第 6 条）：受支持节点有限 + 观测节点保真
        observed_ok = bool(
            np.abs(field[observed] - observed_values[observed]).max(initial=0.0)
            <= _OBSERVED_GATE_TOLERANCE
        )
        if not np.isfinite(field[supported]).all() or not observed_ok:
            raise PlatformError(
                DSI_LIKE_OUTPUT_GATE_VIOLATION,
                "DSI-like 输出门校验失败（有限性或观测保真）",
                {"iterations": iterations, "converged": converged},
            )

        # 6. 残差精确化层：在原始训练坐标上复算趋势场三线性值并建模残差。
        # IDW 在数据点处精确复现 → predict(p_i) = 趋势(p_i) + r_i ≡ v_i。
        trend_only = _DSILikeFitted(
            field=field, axes=axes, lows=lows, highs=highs, residual=None, diagnostics={}
        )
        trend_at_training, trend_nodata = trend_only._sample_chunk(coordinates)
        if trend_nodata.any():
            raise PlatformError(
                DSI_LIKE_CONSTRAINT_VIOLATION,
                "DSI-like 趋势场在原始训练坐标上出现 NoData，无法建立硬约束",
                {"nodata_count": int(trend_nodata.sum())},
            )
        residuals = values - trend_at_training
        residual_model = IDWInterpolator().fit(
            coordinates,
            residuals,
            IDWParameters(power=parameters.init_power, min_neighbors=1),
        )
        fitted = _DSILikeFitted(
            field=field,
            axes=axes,
            lows=lows,
            highs=highs,
            residual=residual_model,
            diagnostics={},
        )

        # 7. 观测点输出门：全部训练点复算误差 ≤ 1e-8，否则 fail-closed
        repro = fitted.predict(coordinates, cancel=cancel)
        if repro.is_nodata.any() or not np.isfinite(repro.values).all():
            max_observation_error = float("inf")
        else:
            max_observation_error = float(
                np.abs(repro.values - values).max(initial=0.0)
            )
        if not max_observation_error <= _CONSTRAINT_GATE_TOLERANCE:  # inf/NaN 均违例
            raise PlatformError(
                DSI_LIKE_CONSTRAINT_VIOLATION,
                "DSI-like 观测点硬约束输出门违例（训练点复算误差超容差）",
                {"max_observation_error": max_observation_error},
            )

        return _DSILikeFitted(
            field=field,
            axes=axes,
            lows=lows,
            highs=highs,
            residual=residual_model,
            diagnostics={
                "iterations": iterations,
                "converged": converged,
                "max_delta": max_delta,
                "supported_count": supported_count,
                "grid_shape": list(shape),
                "max_observation_error": max_observation_error,
            },
        )


def _trilinear_sample(
    field: np.ndarray, axes: tuple[np.ndarray, ...], query: np.ndarray
) -> np.ndarray:
    """三线性采样：角点含 NoData（NaN）则结果 NaN，不外推、不编造。"""

    n = query.shape[0]
    lows_index = np.zeros((n, 3), dtype=np.int64)
    highs_index = np.zeros((n, 3), dtype=np.int64)
    frac = np.zeros((n, 3), dtype="float64")
    for dim, axis in enumerate(axes):
        count = len(axis)
        if count > 1 and axis[-1] > axis[0]:
            step = (axis[-1] - axis[0]) / (count - 1)
            position = np.clip((query[:, dim] - axis[0]) / step, 0.0, count - 1.0)
            lower = np.minimum(np.floor(position).astype(np.int64), count - 1)
            lows_index[:, dim] = lower
            highs_index[:, dim] = np.minimum(lower + 1, count - 1)
            frac[:, dim] = position - lower
    result = np.zeros(n, dtype="float64")
    for cx in (0, 1):
        for cy in (0, 1):
            for cz in (0, 1):
                weight = (
                    np.where(cx, frac[:, 0], 1.0 - frac[:, 0])
                    * np.where(cy, frac[:, 1], 1.0 - frac[:, 1])
                    * np.where(cz, frac[:, 2], 1.0 - frac[:, 2])
                )
                corner = field[
                    np.where(cx, highs_index[:, 0], lows_index[:, 0]),
                    np.where(cy, highs_index[:, 1], lows_index[:, 1]),
                    np.where(cz, highs_index[:, 2], lows_index[:, 2]),
                ]
                result += weight * corner
    return result


@dataclass(frozen=True)
class _DSILikeFitted:
    field: np.ndarray
    axes: tuple[np.ndarray, ...]
    # 观测三维包围盒（物理坐标）；界外查询恒为 NoData
    lows: np.ndarray
    highs: np.ndarray
    # 残差精确化层（原始观测点硬约束）；None 表示纯趋势场（仅 fit 内部过渡）
    residual: _IDWFitted | None
    diagnostics: dict[str, Any]

    def _sample_chunk(self, query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """三线性趋势 + 残差修正（网格采样合同）：界外/角点 NoData → NoData。"""

        trend = _trilinear_sample(self.field, self.axes, query)
        combined = trend
        if self.residual is not None:
            # 残差层只在趋势有值处叠加修正；NoData 语义由趋势层决定
            correction = self.residual.predict(query, cancel=lambda: False)
            combined = trend + correction.values
        outside = np.any((query < self.lows) | (query > self.highs), axis=1)
        is_nodata = outside | ~np.isfinite(combined)
        # 与 IDW 同口径：NoData 目标值为 NaN，绝不回填编造的数
        return np.where(is_nodata, np.nan, combined), is_nodata

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        query = np.asarray(query, dtype="float64")
        if query.ndim != 2 or query.shape[1] != 3:
            raise PlatformError(
                DSI_LIKE_INPUT_INVALID,
                "dsi_like 查询点必须是 (n, 3) 三维坐标",
                {"shape": list(query.shape)},
            )
        n = query.shape[0]
        values = np.full(n, np.nan)
        is_nodata = np.ones(n, dtype=bool)
        for start in range(0, n, PREDICTION_CHUNK_SIZE):
            if cancel():
                raise PlatformError(
                    RUN_CANCELED, "任务已被取消", {"completed": start}, http_status=409
                )
            end = min(start + PREDICTION_CHUNK_SIZE, n)
            chunk_values, chunk_nodata = self._sample_chunk(query[start:end])
            values[start:end] = chunk_values
            is_nodata[start:end] = chunk_nodata
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics={**self.diagnostics, "n_targets": n},
        )

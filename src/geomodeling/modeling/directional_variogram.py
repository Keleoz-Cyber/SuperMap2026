"""Omnidirectional and directional empirical semivariograms (design §6).

经典经验半变异函数 γ(h) = (1/2N(h)) Σ[Z(xi)−Z(xj)]²，只在 Task 2
``sample_pairs`` 返回的采样点对上计算（种子
``seed_from_contract(data_sha256, canonical_config)``，不依赖进程时间）。
bin 边界为 ``linspace(0, max_distance, lag_count+1)``：恰好落在内部边界
上的点对归入下侧 bin（首个 bin 含 0，与实施计划 Task 3 手算示例一致），
最后一个 bin 闭右端；超出 ``max_distance`` 的点对不进入任何 bin，也不会
被夹入末 bin。``max_distance`` 为 None 时取采样点对的最大距离（无点对或
全重合的退化输入回退 1.0）。

每个 bin 披露下界/上界/中心、半变异值、点对数、实际平均距离、方向
（``DirectionSpec``，含方位角/倾角中心与显式容差）、是否参与拟合及排除
原因：低于 ``min_pairs_per_bin`` 的 bin 显示但不进拟合
（``used_for_fit=False`` + ``exclusion_reason``）；方向 bin 点对不足时
标记 ``unsupported_insufficient_pairs``，不外推主方向。

方向归属采用无向锐角判定（``d`` 与 ``-d`` 同向）：2D 只用方位角；3D
同时施加方位角与倾角容差（倾角对无向线取 |dip|）。容差边界含
``ANGLE_BOUNDARY_EPS`` 浮点护栏，判定为包含（≤ tolerance）。零长度点对
（重合点）方向未定义，按方位角 0°/倾角 0° 约定归入；铅直点对的水平投影
为零，方位角同样按 0° 约定处理。结果随 bins 返回采样元数据
（total/used/rate/seed）。不调用 ``scipy.spatial.distance.pdist``，
不分配 n×n 距离矩阵；取消在每个有界批次前检查。

当前合同依据：docs/architecture.md。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from geomodeling.modeling.base import CancelFn
from geomodeling.modeling.pair_sampling import (
    DISTANCE_BATCH_SIZE,
    RUN_CANCELED,
    PairSample,
    sample_pairs,
    seed_from_contract,
)
from geomodeling.modeling.professional_contracts import (
    DirectionSpec,
    VariogramDiagnosticSpec,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension

__all__ = [
    "ANGLE_BOUNDARY_EPS",
    "EXCLUSION_EMPTY_BIN",
    "EXCLUSION_INSUFFICIENT_PAIRS",
    "EXCLUSION_UNSUPPORTED_DIRECTION",
    "RUN_CANCELED",
    "VARIOGRAM_INPUT_INVALID",
    "EmpiricalBin",
    "EmpiricalVariogram",
    "bin_pair_distances",
    "compute_empirical_variogram",
]

VARIOGRAM_INPUT_INVALID = "VARIOGRAM_INPUT_INVALID"

EXCLUSION_EMPTY_BIN = "empty_bin"
EXCLUSION_INSUFFICIENT_PAIRS = "insufficient_pairs"
EXCLUSION_UNSUPPORTED_DIRECTION = "unsupported_insufficient_pairs"

# 角度容差比较的浮点护栏（度）：恰好位于容差边界上的点对被确定性地纳入。
ANGLE_BOUNDARY_EPS = 1e-9


@dataclass(frozen=True)
class EmpiricalBin:
    """单个滞后 bin 的不可变披露记录（§6.1）。

    ``mean_distance`` 为 bin 内点对的实际平均距离，空 bin 为 NaN；
    ``semivariance`` 为 bin 内 ``0.5*(Zi-Zj)**2`` 的均值，空 bin 为 None
    （低于 ``min_pairs_per_bin`` 的 bin 仍披露数值但不进拟合）；
    ``direction`` 为 None 表示全向 bin，否则携带该方向的完整
    ``DirectionSpec``（方位角/倾角中心与显式容差）。
    """

    lower_distance: float
    upper_distance: float
    center_distance: float
    mean_distance: float
    semivariance: float | None
    pair_count: int
    used_for_fit: bool
    exclusion_reason: str | None
    direction: DirectionSpec | None


@dataclass(frozen=True)
class EmpiricalVariogram:
    """全向 + 方向经验半变异函数结果；``sampling`` 披露点对抽样元数据。

    ``directional`` 与 ``spec.directions`` 一一对应，每个元素是该方向的
    bin 元组（每个 bin 的 ``direction`` 字段回指该 ``DirectionSpec``）。
    """

    omnidirectional: tuple[EmpiricalBin, ...]
    directional: tuple[tuple[EmpiricalBin, ...], ...]
    sampling: PairSample


def _never_canceled() -> bool:
    return False


def bin_pair_distances(
    distances: np.ndarray,
    semivariances: np.ndarray,
    edges: np.ndarray,
    *,
    min_pairs_per_bin: int,
    member_mask: np.ndarray | None = None,
    direction: DirectionSpec | None = None,
) -> tuple[EmpiricalBin, ...]:
    """把点对距离/半变异按 ``edges`` 分箱，返回类型化 :class:`EmpiricalBin`。

    内部边界上的距离归入下侧 bin（``searchsorted(..., side="left")``，首
    bin 含 0），末 bin 闭右端；``distances > edges[-1]`` 的点对不进入任何
    bin。``member_mask``（如方向归属掩膜）进一步限制计入的点对子集；
    ``direction`` 原样写入每个 bin 的披露字段。本函数是
    ``modeling.variogram`` legacy 12-bin 路径与方向诊断共用的分箱核心。
    """

    distances = np.asarray(distances, dtype=np.float64)
    semivariances = np.asarray(semivariances, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.float64)
    if distances.ndim != 1 or distances.shape != semivariances.shape:
        raise PlatformError(
            VARIOGRAM_INPUT_INVALID,
            "点对距离与半变异必须为等长一维数组",
            {"distances": list(distances.shape), "semivariances": list(semivariances.shape)},
        )
    if (
        edges.ndim != 1
        or edges.size < 2
        or not np.isfinite(edges).all()
        or edges[0] != 0.0
        or bool((np.diff(edges) <= 0).any())
    ):
        raise PlatformError(
            VARIOGRAM_INPUT_INVALID, "bin 边界必须为从 0 开始的严格递增有限序列"
        )
    if member_mask is not None:
        member_mask = np.asarray(member_mask, dtype=bool)
        if member_mask.shape != distances.shape:
            raise PlatformError(
                VARIOGRAM_INPUT_INVALID, "方向归属掩膜必须与点对数组等长"
            )
    lag_count = edges.size - 1
    indices = np.clip(np.searchsorted(edges, distances, side="left") - 1, 0, lag_count - 1)
    in_range = distances <= edges[-1]
    if member_mask is not None:
        in_range = in_range & member_mask
    directional = direction is not None
    bins: list[EmpiricalBin] = []
    for bin_index in range(lag_count):
        members = in_range & (indices == bin_index)
        count = int(members.sum())
        lower = float(edges[bin_index])
        upper = float(edges[bin_index + 1])
        if count:
            mean_distance = float(distances[members].mean())
            gamma = float(semivariances[members].mean())
        else:
            mean_distance = float("nan")
            gamma = None
        if count >= min_pairs_per_bin:
            used_for_fit, exclusion_reason = True, None
        elif directional:
            used_for_fit, exclusion_reason = False, EXCLUSION_UNSUPPORTED_DIRECTION
        elif count == 0:
            used_for_fit, exclusion_reason = False, EXCLUSION_EMPTY_BIN
        else:
            used_for_fit, exclusion_reason = False, EXCLUSION_INSUFFICIENT_PAIRS
        bins.append(
            EmpiricalBin(
                lower_distance=lower,
                upper_distance=upper,
                center_distance=(lower + upper) / 2.0,
                mean_distance=mean_distance,
                semivariance=gamma,
                pair_count=count,
                used_for_fit=used_for_fit,
                exclusion_reason=exclusion_reason,
                direction=direction,
            )
        )
    return tuple(bins)


def _direction_member_mask(
    points: np.ndarray, indices: np.ndarray, direction: DirectionSpec
) -> np.ndarray:
    """点对的无向方向归属掩膜：2D 仅方位角，3D 方位角与倾角双门控。

    方位角为 XY 平面内 +X 朝 +Y 的角度，模 180°（无向）；3D 倾角取
    |asin(dz/|d|)|（无向线，``d`` 与 ``-d`` 同向）。两个角度分别与
    ``DirectionSpec`` 的显式中心和容差比较，边界按
    ``<= tolerance + ANGLE_BOUNDARY_EPS`` 纳入。
    """

    diffs = points[indices[:, 1]] - points[indices[:, 0]]
    azimuth = np.degrees(np.arctan2(diffs[:, 1], diffs[:, 0])) % 180.0
    azimuth_delta = np.abs((azimuth - direction.azimuth_deg + 90.0) % 180.0 - 90.0)
    mask = azimuth_delta <= direction.azimuth_tolerance_deg + ANGLE_BOUNDARY_EPS
    if direction.dimension == Dimension.THREE_D:
        lengths = np.linalg.norm(diffs, axis=1)
        sin_dip = np.divide(
            diffs[:, 2], lengths, out=np.zeros_like(lengths), where=lengths > 0
        )
        dip = np.degrees(np.arcsin(np.clip(np.abs(sin_dip), 0.0, 1.0)))
        dip_delta = np.abs(dip - abs(float(direction.dip_deg)))
        mask &= dip_delta <= float(direction.dip_tolerance_deg) + ANGLE_BOUNDARY_EPS
    return mask


def _batched_pair_terms(
    points: np.ndarray, values: np.ndarray, indices: np.ndarray, cancel: CancelFn
) -> tuple[np.ndarray, np.ndarray]:
    """按有界批次计算采样点对的距离与 ``0.5*(Zi-Zj)**2``，每批前检查取消。"""

    count = indices.shape[0]
    distances = np.empty(count, dtype=np.float64)
    semivariances = np.empty(count, dtype=np.float64)
    for start in range(0, count, DISTANCE_BATCH_SIZE):
        if cancel():
            raise PlatformError(
                RUN_CANCELED, "任务已被取消", {"completed_pairs": start}, http_status=409
            )
        batch = indices[start : start + DISTANCE_BATCH_SIZE]
        distances[start : start + batch.shape[0]] = np.linalg.norm(
            points[batch[:, 0]] - points[batch[:, 1]], axis=1
        )
        semivariances[start : start + batch.shape[0]] = (
            0.5 * (values[batch[:, 0]] - values[batch[:, 1]]) ** 2
        )
    return distances, semivariances


def compute_empirical_variogram(
    points: np.ndarray,
    values: np.ndarray,
    spec: VariogramDiagnosticSpec,
    *,
    data_sha256: str,
    cancel: CancelFn | None = None,
) -> EmpiricalVariogram:
    """计算全向与方向经验半变异函数（§6），结果披露每个 bin 与采样元数据。

    点对身份只由 ``sample_pairs`` 决定，种子派生自 ``data_sha256`` 与
    规范化诊断配置（``spec.model_dump_json()``）；同一输入与配置产生相同
    点对、曲线与哈希。``spec.directions`` 为空时仅返回全向 bins。
    """

    points = np.asarray(points, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] not in (2, 3):
        raise PlatformError(
            VARIOGRAM_INPUT_INVALID,
            "坐标必须为 (n, 2) 或 (n, 3) 二维数组",
            {"shape": list(points.shape)},
        )
    dimension = Dimension.THREE_D if points.shape[1] == 3 else Dimension.TWO_D
    if values.ndim != 1 or values.shape[0] != points.shape[0]:
        raise PlatformError(
            VARIOGRAM_INPUT_INVALID,
            "属性值必须为一维数组且与坐标行数一致",
            {"points": points.shape[0], "values": list(values.shape)},
        )
    if not np.isfinite(points).all() or not np.isfinite(values).all():
        raise PlatformError(VARIOGRAM_INPUT_INVALID, "坐标与属性值必须全部为有限值")
    for direction in spec.directions:
        if direction.dimension != dimension:
            raise PlatformError(
                VARIOGRAM_INPUT_INVALID,
                "方向定义的维度与坐标维度不一致",
                {"data_dimension": dimension.value, "direction_dimension": direction.dimension},
            )
    cancel_fn = cancel if cancel is not None else _never_canceled

    canonical_config = spec.model_dump_json().encode("utf-8")
    seed = seed_from_contract(data_sha256, canonical_config)
    sample = sample_pairs(points, max_pairs=spec.max_pairs, seed=seed, cancel=cancel_fn)
    distances, semivariances = _batched_pair_terms(
        points, values, sample.indices, cancel_fn
    )

    if spec.max_distance is not None:
        h_max = float(spec.max_distance)
    elif distances.size and float(distances.max()) > 0.0:
        h_max = float(distances.max())
    else:
        h_max = 1.0  # 无点对或全重合的退化输入：披露空/零 bin，不静默失败
    edges = np.linspace(0.0, h_max, spec.lag_count + 1)

    omnidirectional = bin_pair_distances(
        distances, semivariances, edges, min_pairs_per_bin=spec.min_pairs_per_bin
    )
    directional = tuple(
        bin_pair_distances(
            distances,
            semivariances,
            edges,
            min_pairs_per_bin=spec.min_pairs_per_bin,
            member_mask=_direction_member_mask(points, sample.indices, direction),
            direction=direction,
        )
        for direction in spec.directions
    )
    return EmpiricalVariogram(
        omnidirectional=omnidirectional, directional=directional, sampling=sample
    )

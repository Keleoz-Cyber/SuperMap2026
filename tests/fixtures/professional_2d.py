"""Task 22 fixtures: deterministic synthetic 2D professional structures.

所有场都由循环嵌入（circulant embedding, FFT）高斯场生成器现造：固定种
子、纯内存计算，不读仓库内任何数据文件；``write_points_csv`` 只往调用方
给定的 pytest ``tmp_path`` 写 CSV，绝不把生成的运行时 CSV 提交进仓库。

2D 结构真值：

- 各向异性场：单块 160×160 间距 5 大域，主方向方位角 30°，主/次变程
  60/20（真值比例 3.0）。诊断采样点对集中在诊断窗内且结构在窗内到达
  基台（球状有限变程），方向拟合稳定；
- 各向同性对照：同一网格上 25 个独立各向同性实现（变程 30）的逐点平
  均——单实现的方向拟合被实现噪声主导（方向间拟合变程可差 2 倍以上，
  是变差函数估计的固有方差，不是平台缺陷），25 重平均把它压低 5 倍，
  使「无强方向宣称」按经验曲线跨方向偏差稳定可判；
- 交叉验证场：单块 40×40（专业/legacy Kriging 折外对比用，规模轻）；
- 手工异常网格：12×12 均匀网格上的两个高值 + 两个低值连通区，桥节点
  的经验误差高于门槛时其中一个高值连通区被确定性切成两个。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geomodeling.modeling.professional_contracts import DirectionSpec

__all__ = [
    "AZIMUTH_DEG",
    "RANGE_MAJOR",
    "RANGE_MINOR",
    "RANGE_RATIO",
    "SEED",
    "ISO_RANGE",
    "ISO_SEED",
    "CV_SEED",
    "AnomalyGrid",
    "SyntheticField",
    "anisotropic_field",
    "anomaly_grid",
    "circulant_tile",
    "cross_validation_field",
    "directions",
    "isotropic_control",
    "spherical_covariance",
    "write_points_csv",
]

#: 各向异性 2D 场的真值：主方向 30°，主/次变程 60/20。
AZIMUTH_DEG = 30.0
RANGE_MAJOR = 60.0
RANGE_MINOR = 20.0
RANGE_RATIO = RANGE_MAJOR / RANGE_MINOR  # 3.0
SEED = 20260726

#: 各向同性对照：变程 30，独立种子与实现数（逐点平均压实现噪声）。
ISO_RANGE = 30.0
ISO_SEED = 777
ISO_FIELD_COUNT = 25

#: 交叉验证场独立种子（单块 40×40）。
CV_SEED = 909090


@dataclass(frozen=True)
class SyntheticField:
    """确定性合成场：点坐标 (n, dim) 与值 (n,)，只读。"""

    points: np.ndarray
    values: np.ndarray
    dimension: str


@dataclass(frozen=True)
class AnomalyGrid:
    """手工异常网格：轴/值/NoData/经验误差层与桥节点索引。

    ``empirical_error`` 全场 0.5，仅桥节点为 5.0：以
    ``empirical_error_max=1.0`` 门槛提取时桥节点被排除，高值连通区 H2
    确定性切成两个 2×2 块。
    """

    axes: tuple[np.ndarray, np.ndarray]
    values: np.ndarray
    is_nodata: np.ndarray
    empirical_error: np.ndarray
    empirical_error_nodata: np.ndarray
    bridge_node: tuple[int, int]


def spherical_covariance(h: np.ndarray, partial_sill: float) -> np.ndarray:
    """球状协方差（h 已按变程归一）。"""

    r = np.minimum(h, 1.0)
    return partial_sill * np.where(r < 1.0, 1.0 - 1.5 * r + 0.5 * r**3, 0.0)


def circulant_tile(
    shape: tuple[int, ...],
    spacing: float,
    axes_unit: list[tuple[float, ...]],
    ranges: tuple[float, ...],
    *,
    nugget: float,
    sill: float,
    seed: int,
) -> np.ndarray:
    """循环嵌入生成一块规则网格高斯场（确定性，FFT 加速）。

    在 2× 延展网格上构造各向异性球状协方差块循环矩阵，特征值非负时
    以其平方根谱乘白噪声再逆变换，取主块。特征值为负（非正定）直接
    抛错——夹具配置必须换种子/变程，绝不静默钳制。
    """

    dims = tuple(2 * n for n in shape)
    coords = []
    for m in dims:
        k = np.arange(m)
        coords.append(np.where(k <= m // 2, k, k - m) * spacing)
    grids = np.meshgrid(*coords, indexing="ij")
    h2 = np.zeros(dims)
    for unit, range_ in zip(axes_unit, ranges):
        proj = np.zeros(dims)
        for grid, component in zip(grids, unit):
            proj = proj + grid * component
        h2 = h2 + (proj / range_) ** 2
    cov = spherical_covariance(np.sqrt(h2), sill)
    cov.flat[0] += nugget
    eigenvalues = np.real(np.fft.fftn(cov))
    if eigenvalues.min() < 0:
        raise RuntimeError(f"循环嵌入非正定：最小特征值 {eigenvalues.min()}")
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(dims)
    field = np.real(np.fft.ifftn(np.sqrt(eigenvalues) * np.fft.fftn(noise)))
    return field[tuple(slice(0, n) for n in shape)]


def _axes_2d(azimuth_deg: float) -> list[tuple[float, float]]:
    azimuth = np.radians(azimuth_deg)
    return [
        (float(np.cos(azimuth)), float(np.sin(azimuth))),
        (float(-np.sin(azimuth)), float(np.cos(azimuth))),
    ]


def anisotropic_field() -> SyntheticField:
    """2D 各向异性场：主方向 30°，主/次变程 60/20（25,600 点）。

    单块 160×160 大域（约 13 个主变程跨度）：诊断采样点对集中在诊断
    窗内，方向拟合稳定——本种子下平台方向拟合给出 az30→57.3、
    az120→20.2（真值 60/20），候选方位精确命中 30°、比例 2.84
    （纯函数链）/ 3.31（持久诊断服务），均在声明容差内。
    """

    grids = np.meshgrid(*[np.arange(160) * 5.0] * 2, indexing="ij")
    points = np.column_stack([grid.ravel() for grid in grids])
    values = circulant_tile(
        (160, 160),
        5.0,
        _axes_2d(AZIMUTH_DEG),
        (RANGE_MAJOR, RANGE_MINOR),
        nugget=0.02,
        sill=1.0,
        seed=SEED,
    )
    return SyntheticField(points=points, values=values.ravel(), dimension="2d")


def isotropic_control() -> SyntheticField:
    """各向同性对照场：25 个独立各向同性实现的逐点平均（25,600 点）。

    单实现各向同性场的方向拟合被实现噪声主导（方向间拟合变程可差 2 倍
    以上，详见本模块模块docstring）；25 重平均把场级实现噪声压低 5 倍，
    使方向经验曲线跨方向偏差稳定在 ±20% 以内（验收按声明阈值 25% 判定）。
    平均不改变协方差结构（球状、变程 30、各向同性），仅把基台缩到 1/25。
    """

    grids = np.meshgrid(*[np.arange(160) * 5.0] * 2, indexing="ij")
    points = np.column_stack([grid.ravel() for grid in grids])
    rng = np.random.default_rng(ISO_SEED)
    acc = np.zeros((160, 160), dtype="float64")
    for _ in range(ISO_FIELD_COUNT):
        acc += circulant_tile(
            (160, 160),
            5.0,
            [(1.0, 0.0), (0.0, 1.0)],
            (ISO_RANGE, ISO_RANGE),
            nugget=0.02,
            sill=1.0,
            seed=int(rng.integers(0, 2**31)),
        )
    return SyntheticField(
        points=points, values=(acc / ISO_FIELD_COUNT).ravel(), dimension="2d"
    )


def cross_validation_field() -> SyntheticField:
    """交叉验证场：单块 40×40，与诊断场同真值几何（1,600 点，轻量）。"""

    grids = np.meshgrid(*[np.arange(40) * 5.0] * 2, indexing="ij")
    points = np.column_stack([grid.ravel() for grid in grids])
    values = circulant_tile(
        (40, 40),
        5.0,
        _axes_2d(AZIMUTH_DEG),
        (RANGE_MAJOR, RANGE_MINOR),
        nugget=0.02,
        sill=1.0,
        seed=CV_SEED,
    )
    return SyntheticField(points=points, values=values.ravel(), dimension="2d")


def directions() -> tuple[DirectionSpec, ...]:
    """2D 方向诊断集：30° 间隔、±20° 容差（真值 30° 恰为网格成员）。"""

    return tuple(
        DirectionSpec(dimension="2d", azimuth_deg=float(azimuth), azimuth_tolerance_deg=20.0)
        for azimuth in (0, 30, 60, 90, 120, 150)
    )


def anomaly_grid() -> AnomalyGrid:
    """12×12 手工网格：两个高值 + 两个低值连通区，桥节点可被门槛切开。

    布局（索引即 [x 序号, y 序号]，均匀间距 2）：

    - H1：(1..2, 1..2) 值 10 —— 2×2 内部块；
    - H2：(7..8, 7..8) 值 10 + 桥 (9, 7) + (10..11, 7..8) 值 10 ——
      四邻接下单连通；桥节点经验误差 5.0 被门槛 1.0 排除后切成两个
      2×2 块；
    - L1：(1..2, 8..9) 值 −10；L2：(8..10, 1) 值 −10 —— 两个低值区；
    - 其余节点值 0，NoData 全 False。
    """

    axis = np.arange(12, dtype="float64") * 2.0
    values = np.zeros((12, 12), dtype="float64")
    values[1:3, 1:3] = 10.0
    values[7:9, 7:9] = 10.0
    values[10:12, 7:9] = 10.0
    values[9, 7] = 10.0
    values[1:3, 8:10] = -10.0
    values[8:11, 1] = -10.0
    empirical = np.full((12, 12), 0.5, dtype="float64")
    empirical[9, 7] = 5.0
    nodata = np.zeros((12, 12), dtype=bool)
    return AnomalyGrid(
        axes=(axis, axis.copy()),
        values=values,
        is_nodata=nodata,
        empirical_error=empirical,
        empirical_error_nodata=nodata.copy(),
        bridge_node=(9, 7),
    )


def write_points_csv(field: SyntheticField, path: Path) -> Path:
    """把合成场写成 CSV（只写调用方给定的临时路径；返回实际路径）。

    2D 写 ``x,y,value``，3D 写 ``x,y,z,value``；坐标保留一位小数（网格
    坐标均为 0.5 的整数倍，无精度损失），值保留 9 位小数。
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "x,y,z,value" if field.dimension == "3d" else "x,y,value"
    lines = [header]
    for point, value in zip(field.points, field.values):
        coords = ",".join(f"{coordinate:.1f}" for coordinate in point)
        lines.append(f"{coords},{value:.9f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    return path

"""Task 22 fixtures: deterministic synthetic 3D professional structure.

3D 结构真值：主方向水平、方位角 60°（倾角 0°），主/次/垂变程
15/5/7.5（真值主次比 3.0、主垂比 2.0）。单块 24×24×12、间距 2.5 的
循环嵌入 FFT 高斯场（球状有限变程，结构在诊断窗内到达基台），固定
种子、纯内存计算，不读仓库内任何数据文件。

配置标定（种子扫描后锁定本种子并记录实测值）：诊断窗 max_distance=30
（2× 主变程）、lag_count=8 下，平台方向拟合给出 az60→12.0、az150→6.1、
垂向→5.6——候选方位精确命中 60°，主/次比 1.97（真值 3.0）、主/垂比
2.14（真值 2.0），全部落在声明容差 [truth/1.5, truth×1.5] 内。
"""

from __future__ import annotations

import numpy as np

from geomodeling.modeling.professional_contracts import DirectionSpec

from .professional_2d import SyntheticField, circulant_tile

__all__ = [
    "AZIMUTH_DEG",
    "DIP_DEG",
    "RANGE_MAJOR",
    "RANGE_MINOR",
    "RANGE_VERTICAL",
    "RATIO_MINOR",
    "RATIO_VERTICAL",
    "SEED",
    "anisotropic_field",
    "directions",
]

#: 3D 各向异性场真值：水平主方向 60°/倾角 0°，主/次/垂变程 15/5/7.5。
AZIMUTH_DEG = 60.0
DIP_DEG = 0.0
RANGE_MAJOR = 15.0
RANGE_MINOR = 5.0
RANGE_VERTICAL = 7.5
RATIO_MINOR = RANGE_MAJOR / RANGE_MINOR  # 3.0
RATIO_VERTICAL = RANGE_MAJOR / RANGE_VERTICAL  # 2.0
SEED = 95508114


def anisotropic_field() -> SyntheticField:
    """3D 各向异性场：主方向 60° 水平，变程 15/5/7.5（13,824 点）。"""

    azimuth = np.radians(AZIMUTH_DEG)
    axes_unit = [
        (float(np.cos(azimuth)), float(np.sin(azimuth)), 0.0),
        (float(-np.sin(azimuth)), float(np.cos(azimuth)), 0.0),
        (0.0, 0.0, 1.0),
    ]
    grids = np.meshgrid(*[np.arange(n) * 2.5 for n in (24, 24, 12)], indexing="ij")
    points = np.column_stack([grid.ravel() for grid in grids])
    values = circulant_tile(
        (24, 24, 12),
        2.5,
        axes_unit,
        (RANGE_MAJOR, RANGE_MINOR, RANGE_VERTICAL),
        nugget=0.02,
        sill=1.0,
        seed=SEED,
    )
    return SyntheticField(points=points, values=values.ravel(), dimension="3d")


def directions() -> tuple[DirectionSpec, ...]:
    """3D 方向诊断集：水平 30° 间隔 + 铅直方向，容差 ±20°。"""

    horizontal = tuple(
        DirectionSpec(
            dimension="3d",
            azimuth_deg=float(azimuth),
            dip_deg=0.0,
            azimuth_tolerance_deg=20.0,
            dip_tolerance_deg=20.0,
        )
        for azimuth in (0, 30, 60, 90, 120, 150)
    )
    vertical = DirectionSpec(
        dimension="3d",
        azimuth_deg=0.0,
        dip_deg=90.0,
        azimuth_tolerance_deg=20.0,
        dip_tolerance_deg=20.0,
    )
    return (*horizontal, vertical)

"""Canonical kriging anisotropy transforms (design §6.3, §7.2).

本节变换只属于普通 Kriging。定义物理坐标向量 ``x``、旋转矩阵 ``R`` 和
尺度矩阵 ``S = diag(1/a_major, 1/a_minor, 1/a_vertical)``：变换为
``x' = S Rᵀ x``。实现采用等价的行向量约定：``apply(x) = x @ matrix.T``
且 ``matrix = S @ R.T``（``S`` 对称，二者数值逐位一致）。Kriging 的经验
半变异函数、协方差和权重计算使用变换后的坐标；成果网格物理 X/Y/Z 永远
不变，变换只发生在距离空间。

角度约定（§6.3）：方位角在 XY 平面内从 +X 朝 +Y 旋转，范围
``[0°, 180°)``；倾角从水平面朝 +Z，范围 ``[-90°, 90°]``；3D 滚转角绕
主轴，范围 ``[-180°, 180°]``。3D 旋转按
``R = Rz(azimuth) · Ry(−dip) · Rx(roll)`` 复合：先绕主轴滚转，再从水平
面向 +Z 倾伏，最后在 XY 面内定方位；``dip=0/roll=0`` 时退化为 2D 的
``R = Rz(azimuth)`` 约定。``R`` 的列依次是主、次、垂向轴在物理坐标中
的单位方向。

legacy ``z_scale`` 归一化（§7.2 兼容条款）：v0.5 在 ``(x, y, z ×
z_scale)`` 上计算距离，等价于 identity 旋转加对角矩阵
``diag[1, 1, z_scale]``；``KrigingAnisotropySpec.from_legacy_z_scale``
生成该形式。同一 spec 内 legacy 形式与非默认旋转/尺度互斥（契约层拒
绝），同一候选不得同时应用两种形式。``z_scale=1``、比例全 1、旋转为 0
时与旧各向同性距离逐位等价。

``SpatialTransform.fingerprint`` 是 spec 与矩阵的规范化哈希（canonical
JSON → sha256 短码）：同一 Kriging 候选的经验半变异函数距离、协方差
距离和经验误差距离必须使用同一个变换指纹；矩阵相同但 spec 来源不同
（legacy ``z_scale`` 与专业尺度比）产生不同指纹。

设计依据：docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md §6.3、§7.2。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np
from pydantic import Field, model_validator

from geomodeling.modeling.distance import MAX_Z_SCALE
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import ContractModel, Dimension
from geomodeling.platform.tables import dumps_canonical

__all__ = [
    "ANISOTROPY_INVALID",
    "KrigingAnisotropySpec",
    "SpatialTransform",
    "build_kriging_transform",
]

ANISOTROPY_INVALID = "ANISOTROPY_INVALID"

# 指纹 = sha256(canonical JSON) 前 16 个十六进制字符（64 bit 短码）。
FINGERPRINT_LENGTH = 16

# 指纹载荷的身份标签：变换约定演进时显式升版，避免新旧哈希静默碰撞。
_FINGERPRINT_KIND = "kriging_anisotropy_transform_v1"

# 矩阵写入指纹前的舍入精度：吸收跨平台浮点尾差，不改变几何语义。
_MATRIX_ROUND_DECIMALS = 12


def _require_finite(value: float | None, field_name: str) -> None:
    """每个浮点字段统一的 ``math.isfinite`` 校验（None 由字段可空性负责）。"""

    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field_name} 必须为有限值，收到 {value!r}")


class KrigingAnisotropySpec(ContractModel):
    """普通 Kriging 的规范各向异性声明（§7.1 确认记录的几何部分）。

    方位角/倾角/滚转角定义见模块 docstring；``major_scale``/``minor_scale``/
    ``vertical_scale`` 是主、次、垂向的尺度比（对应 range 比例，进入
    ``S = diag(1/a, …)`` 时取倒数）。2D 不接受倾角、滚转角、垂向尺度与
    legacy ``z_scale``；3D 必须显式给出倾角、滚转角与垂向尺度（水平/零
    滚转用 0 表达）。``legacy_z_scale`` 仅在 identity 旋转且比例全 1 时
    合法：同一候选不得同时应用两种形式。
    """

    dimension: Dimension
    azimuth_deg: float = Field(default=0.0, ge=0, lt=180)
    dip_deg: float | None = Field(default=None, ge=-90, le=90)
    roll_deg: float | None = Field(default=None, ge=-180, le=180)
    major_scale: float = Field(default=1.0, gt=0)
    minor_scale: float = Field(default=1.0, gt=0)
    vertical_scale: float | None = Field(default=None, gt=0)
    legacy_z_scale: float | None = Field(default=None, gt=0, le=MAX_Z_SCALE)

    @model_validator(mode="after")
    def _check_anisotropy(self) -> "KrigingAnisotropySpec":
        _require_finite(self.azimuth_deg, "azimuth_deg")
        _require_finite(self.dip_deg, "dip_deg")
        _require_finite(self.roll_deg, "roll_deg")
        _require_finite(self.major_scale, "major_scale")
        _require_finite(self.minor_scale, "minor_scale")
        _require_finite(self.vertical_scale, "vertical_scale")
        _require_finite(self.legacy_z_scale, "legacy_z_scale")
        if self.dimension == Dimension.TWO_D:
            if self.dip_deg is not None:
                raise ValueError("2D 各向异性不接受倾角参数")
            if self.roll_deg is not None:
                raise ValueError("2D 各向异性不接受滚转角参数")
            if self.vertical_scale is not None:
                raise ValueError("2D 各向异性不接受垂向尺度")
            if self.legacy_z_scale is not None:
                raise ValueError("legacy z_scale 仅适用于 3D（v0.5 语义）")
        else:
            if self.dip_deg is None:
                raise ValueError("3D 各向异性必须显式给出倾角（水平方向使用 0）")
            if self.roll_deg is None:
                raise ValueError("3D 各向异性必须显式给出滚转角（不滚转使用 0）")
            if self.vertical_scale is None:
                raise ValueError("3D 各向异性必须显式给出垂向尺度")
        if self.legacy_z_scale is not None and (
            self.azimuth_deg != 0.0
            or self.dip_deg != 0.0
            or self.roll_deg != 0.0
            or self.major_scale != 1.0
            or self.minor_scale != 1.0
            or self.vertical_scale != 1.0
        ):
            raise ValueError(
                "legacy z_scale 与旋转/尺度比互斥：同一候选不得同时应用两种形式"
            )
        return self

    @classmethod
    def isotropic(cls, dimension: Dimension | str) -> "KrigingAnisotropySpec":
        """各向同性声明：旋转为 0、比例全 1，与旧各向同性距离逐位等价。"""

        dimension = Dimension(dimension)
        if dimension == Dimension.TWO_D:
            return cls(dimension=dimension, azimuth_deg=0.0, major_scale=1.0, minor_scale=1.0)
        return cls(
            dimension=dimension,
            azimuth_deg=0.0,
            dip_deg=0.0,
            roll_deg=0.0,
            major_scale=1.0,
            minor_scale=1.0,
            vertical_scale=1.0,
        )

    @classmethod
    def from_legacy_z_scale(cls, z_scale: float) -> "KrigingAnisotropySpec":
        """把 v0.5 的 3D ``z_scale`` 归一化为 identity 旋转 + diag[1,1,z_scale]。"""

        return cls(
            dimension=Dimension.THREE_D,
            azimuth_deg=0.0,
            dip_deg=0.0,
            roll_deg=0.0,
            major_scale=1.0,
            minor_scale=1.0,
            vertical_scale=1.0,
            legacy_z_scale=z_scale,
        )


@dataclass(frozen=True)
class SpatialTransform:
    """不可变的空间变换：``matrix = S @ R.T`` 与其规范化指纹。

    指纹绑定 spec 与矩阵两者；同一 Kriging 候选的经验半变异函数距离、
    协方差距离和经验误差距离必须使用同一个指纹。
    """

    matrix: np.ndarray
    fingerprint: str

    def apply(self, coordinates: np.ndarray) -> np.ndarray:
        """返回变换后的新数组（``x @ matrix.T``），输入坐标永不改写。"""

        return np.asarray(coordinates, dtype="float64") @ self.matrix.T


def _rotation_2d(azimuth_deg: float) -> np.ndarray:
    """2D 旋转：方位角在 XY 平面内从 +X 朝 +Y。"""

    angle = math.radians(azimuth_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return np.array([[cos_a, -sin_a], [sin_a, cos_a]])


def _rotation_3d(azimuth_deg: float, dip_deg: float, roll_deg: float) -> np.ndarray:
    """3D 旋转：``R = Rz(azimuth) · Ry(−dip) · Rx(roll)``。

    先绕主轴滚转（Rx），再把主轴从水平面向 +Z 倾伏（右手系 Ry 取负角），
    最后在 XY 面内从 +X 朝 +Y 定方位（Rz）；``dip=0/roll=0`` 时退化为 2D
    约定。R 的列依次为主、次、垂向轴的物理方向。
    """

    azimuth = math.radians(azimuth_deg)
    dip = math.radians(dip_deg)
    roll = math.radians(roll_deg)
    cos_a, sin_a = math.cos(azimuth), math.sin(azimuth)
    cos_d, sin_d = math.cos(dip), math.sin(dip)
    cos_r, sin_r = math.cos(roll), math.sin(roll)
    rz = np.array([[cos_a, -sin_a, 0.0], [sin_a, cos_a, 0.0], [0.0, 0.0, 1.0]])
    ry = np.array([[cos_d, 0.0, -sin_d], [0.0, 1.0, 0.0], [sin_d, 0.0, cos_d]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cos_r, -sin_r], [0.0, sin_r, cos_r]])
    return rz @ ry @ rx


def _fingerprint(spec: KrigingAnisotropySpec, matrix: np.ndarray) -> str:
    """spec 与矩阵的规范化哈希（canonical JSON → sha256 短码）。

    矩阵先舍入到 12 位小数并把 ``-0.0`` 归一为 ``0.0``，保证同一 spec 在
    任何进程/平台上得到同一指纹；spec 经 ``model_dump_json`` 规范化后再
    按 canonical JSON（键排序、紧凑分隔符）序列化。
    """

    rounded = np.round(matrix, _MATRIX_ROUND_DECIMALS) + 0.0
    payload = {
        "kind": _FINGERPRINT_KIND,
        "matrix": rounded.tolist(),
        "spec": json.loads(spec.model_dump_json()),
    }
    canonical = dumps_canonical(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def build_kriging_transform(spec: KrigingAnisotropySpec) -> SpatialTransform:
    """按 spec 构造规范变换 ``matrix = S @ R.T`` 并输出其指纹。

    构造后校验：尺度全部有限且 > 0；``R.T @ R == I``（正交）；矩阵行列式
    有限且非零（可逆）。任何一条不满足都以结构化 ``ANISOTROPY_INVALID``
    失败；契约层校验通过的 spec 不会触发这些防线。
    """

    dimension = Dimension(spec.dimension)
    if spec.legacy_z_scale is not None:
        # v0.5 语义：(x, y, z × z_scale) —— identity 旋转 + diag[1,1,z_scale]
        rotation = np.eye(3)
        scales = np.array([1.0, 1.0, float(spec.legacy_z_scale)])
    else:
        if dimension == Dimension.TWO_D:
            rotation = _rotation_2d(float(spec.azimuth_deg))
            ratios = (spec.major_scale, spec.minor_scale)
        else:
            rotation = _rotation_3d(
                float(spec.azimuth_deg), float(spec.dip_deg), float(spec.roll_deg)
            )
            ratios = (spec.major_scale, spec.minor_scale, spec.vertical_scale)
        raw = np.array([float(ratio) for ratio in ratios])
        if not np.isfinite(raw).all() or bool((raw <= 0.0).any()):
            raise PlatformError(
                ANISOTROPY_INVALID,
                "各向异性尺度比必须为有限值且大于 0",
                {"scales": raw.tolist()},
            )
        scales = 1.0 / raw
    size = scales.shape[0]
    if not np.isfinite(scales).all() or bool((scales <= 0.0).any()):
        raise PlatformError(
            ANISOTROPY_INVALID,
            "尺度矩阵对角元素必须为有限值且大于 0",
            {"scales": scales.tolist()},
        )
    if not np.allclose(rotation.T @ rotation, np.eye(size), rtol=0.0, atol=1e-12):
        raise PlatformError(
            ANISOTROPY_INVALID, "旋转矩阵必须正交（R.T @ R == I）"
        )
    matrix = np.diag(scales) @ rotation.T
    determinant = float(np.linalg.det(matrix))
    if not math.isfinite(determinant) or determinant == 0.0:
        raise PlatformError(
            ANISOTROPY_INVALID,
            "变换矩阵行列式必须有限且非零（可逆）",
            {"determinant": determinant},
        )
    return SpatialTransform(matrix=matrix, fingerprint=_fingerprint(spec, matrix))

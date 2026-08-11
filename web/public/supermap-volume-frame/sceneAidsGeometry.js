// v0.9.0 V6 Task 5：XYZ 坐标架几何（纯函数模块，无浏览器依赖）。
//
// 合同（设计 §6.2）：
//   - 原点放在包围盒外侧，水平/垂直方向保留约 8%–12% 最大跨度间距；
//   - X/Y/Z 轴显示长度为对应包围盒跨度的 1.2–1.3 倍；
//   - 深度刻度为独立 Z 标尺（与 Z 轴平行但独立偏移），不复用包围盒边；
//   - 只改变显示位置，不改变数据坐标或分析合同。
//
// 单位：bounds 为度（display-anchor 经纬），zBounds 为米；局部 z 值 =
// display 高度 − anchorHeight。app.js 与本模块同版本部署（帧内容哈希覆盖）。

export const AXIS_GAP_FRACTION_XY = 0.1 // 水平外移：对应跨度的 10%
export const AXIS_GAP_FRACTION_Z = 0.08 // 垂直下移：Z 跨度的 8%
export const AXIS_LENGTH_RATIO = 1.25 // 轴长 = 包围盒跨度 × 1.25（合同 1.2–1.3）
export const DEPTH_TICK_GAP_FRACTION = 0.06 // 深度标尺相对轴原点再外移（-Y）
export const DEPTH_TICK_COUNT = 5

/**
 * @param {{west:number,south:number,east:number,north:number}} bounds 体盒（度）
 * @param {[number, number]} zBounds 体盒 Z 范围（米，display 高度）
 * @param {number} anchorHeight display-anchor 锚点高度（米）
 */
export function computeSceneAidsGeometry(bounds, zBounds, anchorHeight) {
  const lonSpan = bounds.east - bounds.west
  const latSpan = bounds.north - bounds.south
  const zSpan = zBounds[1] - zBounds[0]
  if (
    !Number.isFinite(lonSpan) ||
    !Number.isFinite(latSpan) ||
    !Number.isFinite(zSpan) ||
    lonSpan <= 0 ||
    latSpan <= 0 ||
    zSpan <= 0
  ) {
    throw new Error('SCENE_AIDS_GEOMETRY_INVALID：包围盒跨度必须是正的有限数值')
  }
  if (!Number.isFinite(anchorHeight)) {
    throw new Error('SCENE_AIDS_GEOMETRY_INVALID：anchorHeight 必须是有限数值')
  }

  const origin = [
    bounds.west - lonSpan * AXIS_GAP_FRACTION_XY,
    bounds.south - latSpan * AXIS_GAP_FRACTION_XY,
    zBounds[0] - zSpan * AXIS_GAP_FRACTION_Z,
  ]
  const axes = {
    x: { from: origin, to: [origin[0] + lonSpan * AXIS_LENGTH_RATIO, origin[1], origin[2]] },
    y: { from: origin, to: [origin[0], origin[1] + latSpan * AXIS_LENGTH_RATIO, origin[2]] },
    z: { from: origin, to: [origin[0], origin[1], origin[2] + zSpan * AXIS_LENGTH_RATIO] },
  }

  // 深度刻度：独立 Z 标尺，沿 -Y 再外移（不与 Z 轴同位、不贴包围盒边）；
  // 覆盖真实体元 Z 范围（zBounds），标签展示局部 z 值
  const tickLat = origin[1] - latSpan * DEPTH_TICK_GAP_FRACTION
  const depthTicks = []
  for (let i = 0; i < DEPTH_TICK_COUNT; i += 1) {
    const height = zBounds[0] + (zSpan * i) / (DEPTH_TICK_COUNT - 1)
    depthTicks.push({
      position: [origin[0], tickLat, height],
      localZ: height - anchorHeight,
    })
  }

  return {
    origin,
    axes,
    depthTicks,
    originOutsideBounds:
      origin[0] < bounds.west && origin[1] < bounds.south && origin[2] < zBounds[0],
    axisLengthRatios: {
      x: AXIS_LENGTH_RATIO,
      y: AXIS_LENGTH_RATIO,
      z: AXIS_LENGTH_RATIO,
    },
  }
}

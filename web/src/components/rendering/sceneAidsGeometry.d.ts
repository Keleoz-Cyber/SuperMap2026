// v0.9.0 V6 Task 5：sceneAidsGeometry.js（纯 ESM JS 模块）的类型声明。
// 该模块同时被 app.js（浏览器）与 vitest（jsdom）使用；声明与实现逐字段一致。
declare module '*/supermap-volume-frame/sceneAidsGeometry.js' {
  export const AXIS_GAP_FRACTION_XY: number
  export const AXIS_GAP_FRACTION_Z: number
  export const AXIS_LENGTH_RATIO: number
  export const DEPTH_TICK_GAP_FRACTION: number
  export const DEPTH_TICK_COUNT: number

  export interface SceneAidsBounds {
    west: number
    south: number
    east: number
    north: number
  }

  export interface SceneAidsGeometry {
    origin: [number, number, number]
    axes: {
      x: { from: [number, number, number]; to: [number, number, number] }
      y: { from: [number, number, number]; to: [number, number, number] }
      z: { from: [number, number, number]; to: [number, number, number] }
    }
    depthTicks: Array<{ position: [number, number, number]; localZ: number }>
    originOutsideBounds: boolean
    axisLengthRatios: { x: number; y: number; z: number }
  }

  export function computeSceneAidsGeometry(
    bounds: SceneAidsBounds,
    zBounds: [number, number],
    anchorHeight: number,
  ): SceneAidsGeometry
}

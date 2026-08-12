declare module '*/supermap-volume-frame/cameraRangePolicy.js' {
  export function cameraRangeBounds(spanMetres: number): [number, number]
  export function clampCameraRange(rangeMetres: number, spanMetres: number): number
  export function nextWheelCameraRange(
    rangeMetres: number,
    spanMetres: number,
    deltaY: number,
  ): number
}

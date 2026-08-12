const MIN_RANGE_FACTOR = 0.9
const MAX_RANGE_FACTOR = 4.5
const WHEEL_STEP_FACTOR = 1.08

function finitePositive(value, name) {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} must be finite and positive`)
  return value
}

export function cameraRangeBounds(spanMetres) {
  const span = finitePositive(spanMetres, 'spanMetres')
  return [span * MIN_RANGE_FACTOR, span * MAX_RANGE_FACTOR]
}

export function clampCameraRange(rangeMetres, spanMetres) {
  const range = finitePositive(rangeMetres, 'rangeMetres')
  const [minimum, maximum] = cameraRangeBounds(spanMetres)
  return Math.min(maximum, Math.max(minimum, range))
}

export function nextWheelCameraRange(rangeMetres, spanMetres, deltaY) {
  const direction = Number(deltaY)
  if (!Number.isFinite(direction) || direction === 0) {
    return clampCameraRange(rangeMetres, spanMetres)
  }
  const next = direction > 0 ? rangeMetres * WHEEL_STEP_FACTOR : rangeMetres / WHEEL_STEP_FACTOR
  return clampCameraRange(next, spanMetres)
}

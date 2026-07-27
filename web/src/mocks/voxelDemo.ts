import type { VoxelCells } from '../api/types'

// 公开合成夹具：双峰高斯值场，仅按公开合同（7×21×48、result_id 等）构造，
// 不含任何私有 S3M 缓存字节，用于 Playwright 冒烟驱动 /volume-demo 页面。
export function buildVoxelDemoFixture(): VoxelCells {
  const xs = Array.from({ length: 7 }, (_, i) => -160 + i * (720 / 42))
  const fullY = Array.from({ length: 23 }, (_, i) => 239.13 + i * (420.87 / 22))
  const ys = fullY.filter((_, i) => i !== 1 && i !== 15)
  const zs = Array.from({ length: 48 }, (_, i) => -840 + i * (805.714 / 47))
  const x: number[] = []
  const y: number[] = []
  const z: number[] = []
  const values: number[] = []
  for (const zv of zs) {
    for (const yv of ys) {
      for (const xv of xs) {
        const dx = (xv + 105) / 38
        const dy = (yv - 455) / 125
        const dz = (zv + 420) / 270
        const first = 88 * Math.exp(-(dx * dx + dy * dy + dz * dz))
        const second = 42 * Math.exp(-((dx + 0.8) ** 2 + (dy - 0.6) ** 2 + (dz + 0.4) ** 2))
        x.push(Number(xv.toFixed(3)))
        y.push(Number(yv.toFixed(3)))
        z.push(Number(zv.toFixed(3)))
        values.push(Number((3 + first + second).toFixed(4)))
      }
    }
  }
  return {
    case_id: 'resistivity',
    result_id: 'RHO_KRIG_FINAL_20M_40',
    source: 'iserver_s3m_cache',
    local_cache_label: 'public_generated_fixture',
    local_cache_present: false,
    local_cache_note: 'E2E public generated fixture',
    service_url: 'http://mock.test/iserver/services/volume/rest/realspace',
    tile_files: 26,
    fetched_bytes: 53487,
    count: values.length,
    value_field: 'RHO',
    unit_note: 'RHO 单位待来源确认',
    x,
    y,
    z,
    values,
    x_range: [Math.min(...x), Math.max(...x)],
    y_range: [Math.min(...y), Math.max(...y)],
    z_range: [Math.min(...z), Math.max(...z)],
    value_range: [Math.min(...values), Math.max(...values)],
    registry_facts: {
      rows_columns_bands: [7, 23, 42],
      cell_exact_value_range: [1.418283, 133.146194],
      note: 'public registry facts only',
    },
  }
}

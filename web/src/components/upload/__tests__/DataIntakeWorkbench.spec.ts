import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  DatasetVersionRecord,
  InspectionResult,
  QualityReport,
} from '../../../api/types'
import DataIntakeWorkbench from '../DataIntakeWorkbench.vue'

// v0.9.0 Task 7：数据接入与准备同屏工作台合同。
// 四阶段同屏（文件接入/字段映射/质量检查/建模确认）；组件不直接调用 API，
// 只消费 DTO 并向上抛出回调；空间预览只用映射后的有限值；未知坐标声明
// local_linear，绝不提议 EPSG。

function datasetOf(status: DatasetVersionRecord['status']): DatasetVersionRecord {
  return {
    id: 'ds-1',
    case_id: 'case-1',
    version: 1,
    status,
    profile: {
      original_filename: 'samples.csv',
      size_bytes: 2048,
      source_sha256: 'a'.repeat(64),
      ...(status === 'mapped' || status === 'validated'
        ? { mapping: { x: 'Easting', y: 'Northing', z: 'Depth', value: 'RHO', value_name: '电阻率' } }
        : {}),
    },
    created_at: '2026-08-01T00:00:00+00:00',
  }
}

const INSPECTION: InspectionResult = {
  dataset_id: 'ds-1',
  case_id: 'case-1',
  suffix: '.csv',
  sheet: null,
  columns: [
    { name: 'Easting', inferred_type: 'number' },
    { name: 'Northing', inferred_type: 'number' },
    { name: 'Depth', inferred_type: 'number' },
    { name: 'RHO', inferred_type: 'number' },
  ],
  preview_rows: [
    { Easting: 0, Northing: 0, Depth: -10, RHO: 12.5 },
    { Easting: 100, Northing: 50, Depth: -20, RHO: 30.1 },
    { Easting: 200, Northing: 100, Depth: -30, RHO: 55.0 },
  ],
  row_count: 3,
  candidate_mapping: { x: 'Easting', y: 'Northing', z: 'Depth', value: 'RHO', value_name: 'RHO' },
  limits: { max_upload_bytes: 52428800, max_upload_rows: 500000 },
  profile: {},
}

const XLSX_INSPECTION: InspectionResult = {
  ...INSPECTION,
  suffix: '.xlsx',
  sheet: 'Sheet1',
  sheets: ['Sheet1', 'Sheet2'],
}

const QUALITY: QualityReport = {
  status: 'warnings',
  checks: [],
  issues: [
    { code: 'DUPLICATE_COORDINATES', kind: 'warning', message: '存在 2 组重复坐标', details: {} },
    { code: 'VALUE_NON_NUMERIC', kind: 'blocker', message: '属性列存在非数值', details: {} },
  ],
  statistics: {
    ranges: { x: [0, 200], y: [0, 100], z: [-30, -10] },
    unique_coordinate_count: 3,
    duplicate_count: 2,
    conflict_count: 0,
  },
  valid_row_count: 96,
  invalid_row_count: 4,
  row_count: 100,
  source_sha256: 'a'.repeat(64),
  standardized_sha256: 'b'.repeat(64),
  confirmed: false,
  confirmed_issue_codes: [],
}

function mountWorkbench(overrides: {
  dataset?: DatasetVersionRecord
  inspection?: InspectionResult | null
  report?: QualityReport | null
  conversion?: { valid: number; invalid: number; total: number } | null
}) {
  return mount(DataIntakeWorkbench, {
    props: {
      dataset: overrides.dataset ?? datasetOf('uploaded'),
      inspection: overrides.inspection === undefined ? INSPECTION : overrides.inspection,
      report: overrides.report === undefined ? null : overrides.report,
      conversion: overrides.conversion === undefined ? null : overrides.conversion,
      submitting: false,
      validating: false,
      confirming: false,
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('DataIntakeWorkbench', () => {
  it('四个阶段标签同屏存在：文件接入/字段映射/质量检查/建模确认', () => {
    const wrapper = mountWorkbench({})
    expect(wrapper.get('[data-test="intake-stage-file"]').text()).toContain('文件接入')
    expect(wrapper.get('[data-test="intake-stage-mapping"]').text()).toContain('字段映射')
    expect(wrapper.get('[data-test="intake-stage-quality"]').text()).toContain('质量检查')
    expect(wrapper.get('[data-test="intake-stage-confirm"]').text()).toContain('建模确认')
  })

  it('CSV 已上传：映射阶段激活，文件预览与映射区同屏', () => {
    const wrapper = mountWorkbench({})
    expect(wrapper.get('[data-test="intake-stage-mapping"]').attributes('data-state')).toBe('active')
    expect(wrapper.find('[data-test="step-file"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="step-mapping"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('samples.csv')
  })

  it('XLSX 多工作表：工作表选择器可见并向上抛出 sheet-change', async () => {
    const wrapper = mountWorkbench({ inspection: XLSX_INSPECTION })
    const select = wrapper.get('[data-test="sheet-select"]')
    await select.setValue('Sheet2')
    expect(wrapper.emitted('sheet-change')).toEqual([['Sheet2']])
  })

  it('映射完成前空间预览为解释性引导，不渲染散点', () => {
    const wrapper = mountWorkbench({ inspection: { ...INSPECTION, candidate_mapping: {} } })
    expect(wrapper.get('[data-test="spatial-preview-empty"]').text()).toContain('映射')
    expect(wrapper.find('[data-test="spatial-point"]').exists()).toBe(false)
  })

  it('3D 候选映射：空间预览用预览行有限值渲染散点并显示 Z 范围', () => {
    const wrapper = mountWorkbench({})
    const points = wrapper.findAll('[data-test="spatial-point"]')
    expect(points.length).toBe(3)
    expect(wrapper.get('[data-test="spatial-z-range"]').text()).toContain('Z ∈')
  })

  it('2D 映射：空间预览不出现 Z 范围行', () => {
    const wrapper = mountWorkbench({
      inspection: {
        ...INSPECTION,
        candidate_mapping: { x: 'Easting', y: 'Northing', value: 'RHO' },
      },
    })
    expect(wrapper.findAll('[data-test="spatial-point"]').length).toBe(3)
    expect(wrapper.find('[data-test="spatial-z-range"]').exists()).toBe(false)
  })

  it('坐标声明只给局部/投影选项，绝不提议 EPSG 代码', () => {
    const wrapper = mountWorkbench({})
    const kindSelect = wrapper.get('[data-test="mapping-coordinate-kind"]')
    expect(kindSelect.text()).toContain('局部线性坐标')
    expect(wrapper.text()).not.toMatch(/EPSG:?\s*\d{4,}/)
  })

  it('数值转换失败计数如实显示', () => {
    const wrapper = mountWorkbench({ conversion: { valid: 90, invalid: 10, total: 100 } })
    expect(wrapper.get('[data-test="conversion-result"]').text()).toContain('失败 10 行')
  })

  it('重复坐标警告与非数值阻断在质量摘要中分级展示', () => {
    const wrapper = mountWorkbench({ dataset: datasetOf('mapped'), report: QUALITY })
    const text = wrapper.get('[data-test="quality-composition"]').text()
    expect(text).toContain('DUPLICATE_COORDINATES')
    expect(text).toContain('VALUE_NON_NUMERIC')
    expect(wrapper.get('[data-test="quality-blocker-count"]').text()).toContain('1')
    expect(wrapper.get('[data-test="quality-warning-count"]').text()).toContain('1')
    // 环图仅有效/无效部分-整体口径
    expect(wrapper.get('[data-test="quality-donut"]').text()).toContain('96')
  })

  it('恢复已映射数据版本：质量阶段激活，不重复要求映射', () => {
    const wrapper = mountWorkbench({ dataset: datasetOf('mapped'), report: QUALITY })
    expect(wrapper.get('[data-test="intake-stage-quality"]').attributes('data-state')).toBe('active')
    expect(wrapper.find('[data-test="step-quality"]').exists()).toBe(true)
  })

  it('回调透传：映射提交与质量校验由父级执行', async () => {
    const wrapper = mountWorkbench({ dataset: datasetOf('mapped'), report: QUALITY })
    await wrapper.get('[data-test="run-validate-again"]').trigger('click')
    expect(wrapper.emitted('validate')).toHaveLength(1)
    await flushPromises()
  })
})

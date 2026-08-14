import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'
import { MOCK_VOLUME_FRAME_HTML } from './mockVolumeFrame'

// v0.9.0 Task 6-10 前端 Mock E2E：成果级分析工作台全链路。
// 验证：成果分析按 result_id 获取（identity 绑定）、A/B 组件标注进入 INIT
// 状态、研判点击 → FOCUS_ANNOTATION、相机预设命令、三维反选高亮、权威切片
// 统计共享、AI 空态→生成→四视角→evidence ref 联动、证据带七标签与来源标注。
// iframe 由协议 mock 页面扮演（无 SuperMap3D SDK）：只证明协议与产品接线，
// 绝不宣称真实渲染。

interface MockFrameMessage {
  type: string
  annotationId?: string
  preset?: string
  state?: {
    revision: number
    annotations?: Array<{ id: string; label: string; visible: boolean }>
    focusedAnnotationId?: string | null
    sceneAids?: { axes: boolean; depthTicks: boolean }
  }
}

const EVIDENCE_DIR = '../docs/evidence/v0.9.0-result-analysis-mock'

test.describe('成果级分析工作台（mock 协议帧）', () => {
  test.use({ viewport: { width: 1920, height: 1080 } })

  test('分析接入、组件/相机/切片/AI 联动与证据带', async ({ page }) => {
    await installMockApi(page)
    await page.route(
      (url) => url.pathname === '/supermap-volume-frame/index.html',
      (route) => route.fulfill({ status: 200, contentType: 'text/html', body: MOCK_VOLUME_FRAME_HTML }),
    )

    await page.goto('/#/results/cand-1')
    await expect(page.getByTestId('native-volume-panel')).toBeVisible()

    // 成果级分析按 result_id 获取：领域卡片明确事实→解释→影响→核查链
    await expect(page.getByTestId('side-tab-rules')).toHaveText('地质研判')
    await expect(page.getByTestId('domain-overview')).toContainText('地下电性结构')
    const lowCard = page.getByTestId('domain-card-low-1000001')
    await expect(lowCard).toContainText('低阻异常区')
    await expect(lowCard).toContainText('可能解释')
    await expect(lowCard).toContainText('潜在影响')
    await expect(lowCard).toContainText('建议核查')
    await expect(lowCard).toContainText('不能直接认定为含水区')
    // 技术证据默认收起，仍可追溯原有发现与 A/B 组件
    await expect(page.getByTestId('result-interpretation')).toContainText('最大高值连通区为 A 区')
    await expect(page.getByTestId('component-1')).toContainText('网格支持体积估计')
    await expect(page.getByTestId('component-2')).toContainText('接触边界')
    // 成果概览：组成与阈值来自后端（25%/50% 与 [15,35]）
    const overview = page.getByTestId('interpretation-overview')
    await expect(overview).toContainText('成果网格')
    await expect(overview).toContainText('25.0%')

    // 显式创建渲染资产 → 协议握手
    await page.getByTestId('create-asset').click()
    await expect(page.getByTestId('volume-phase')).toContainText('已渲染')
    const frame = page.frames().find((f) => f.url().includes('/supermap-volume-frame/index.html'))
    expect(frame).toBeTruthy()
    const frameMessages = async () =>
      (await frame!.evaluate(
        () => (window as unknown as { __GMP_MOCK_FRAME__: { received: MockFrameMessage[] } })
          .__GMP_MOCK_FRAME__.received,
      )) as MockFrameMessage[]

    // INIT 初始状态携带组件标注（与研判区同一响应，ID 一致）与场景辅助
    const init = (await frameMessages()).find((m) => m.type === 'INIT')
    expect(init?.state?.annotations?.map((a) => a.id)).toEqual([
      'component-1',
      'component-2',
      'component-1000001',
    ])
    expect(init?.state?.annotations?.[0]).toMatchObject({ label: 'A', visible: true })
    expect(init?.state?.annotations?.[2]).toMatchObject({
      label: '低-A',
      color: '#48a9ff',
      visible: true,
    })
    expect(init?.state?.sceneAids).toEqual({ axes: true, depthTicks: true })

    // 研判区点击组件 B → FOCUS_ANNOTATION + 状态聚焦 + 高亮
    await page.getByTestId('technical-evidence').locator('summary').click()
    await page.getByTestId('component-2').click()
    await expect(page.getByTestId('component-2')).toHaveClass(/focused/)
    await expect
      .poll(async () =>
        (await frameMessages())
          .filter((m) => m.type === 'FOCUS_ANNOTATION')
          .map((m) => m.annotationId)
          .at(-1),
      )
      .toBe('component-2')
    await expect
      .poll(async () => {
        const applied = (await frameMessages()).filter((m) => m.type === 'APPLY_RENDER_STATE')
        return applied.at(-1)?.state?.focusedAnnotationId ?? null
      })
      .toBe('component-2')

    // 相机预设命令到达子帧
    await page.getByTestId('camera-top-xy').click()
    await expect
      .poll(async () =>
        (await frameMessages())
          .filter((m) => m.type === 'SET_CAMERA_PRESET')
          .map((m) => m.preset)
          .at(-1),
      )
      .toBe('top-xy')

    // 三维标注点击反选：mock 帧模拟选择 A → 研判区 A 高亮、B 取消
    await frame!.evaluate(() =>
      (window as unknown as { __GMP_MOCK_SELECT__: (id: string) => void }).__GMP_MOCK_SELECT__(
        'component-1',
      ),
    )
    await expect(page.getByTestId('component-1')).toHaveClass(/focused/)
    await expect(page.getByTestId('component-2')).not.toHaveClass(/focused/)

    // 领域低阻卡片定位同一低值组件身份，不与高值 ID 冲突
    await page.getByTestId('domain-locate-1000001').click()
    await expect
      .poll(async () =>
        (await frameMessages())
          .filter((m) => m.type === 'FOCUS_ANNOTATION')
          .map((m) => m.annotationId)
          .at(-1),
      )
      .toBe('component-1000001')

    // 首屏截图（体积模式 + 组件标注 + 研判区 + 证据带）；先回顶部
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: `${EVIDENCE_DIR}/01-workbench-volume.png` })

    // 切片模式：权威统计共享完整网格阈值（27.3%/45.5%），证据带切片联动
    await page.getByTestId('mode-slice').click()
    await expect(page.getByTestId('slice-coordinate')).toContainText('Z = -400')
    await expect(page.getByTestId('interpretation-slice')).toContainText('27.3%')
    await expect(page.getByTestId('interpretation-slice')).toContainText('45.5%')
    await expect(page.getByTestId('interpretation-slice')).toContainText('+2.3')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: `${EVIDENCE_DIR}/02-workbench-slice.png` })

    // 成果分析四标签（V6 归组：成果概览/切片分析/模型可信度/数据与导出）
    await page.getByTestId('ge-tab-overview').click()
    await expect(page.getByTestId('ge-pane-overview')).toContainText('45.1%')
    await page.getByTestId('ge-tab-slices').click()
    await expect(page.getByTestId('ge-slice-heatmap')).toBeVisible()
    await expect(page.getByTestId('ge-pane-slices')).toContainText('网格支持体积估计')
    await page.getByTestId('ge-tab-model').click()
    await expect(page.getByTestId('ge-pane-model')).toContainText('RMSE')
    await page.getByTestId('ge-tab-provenance').click()
    await expect(page.getByTestId('ge-pane-provenance')).toContainText('输入样本')
    await expect(page.getByTestId('ge-pane-provenance')).toContainText('result_analysis.v2')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: `${EVIDENCE_DIR}/03-evidence-provenance.png` })

    // AI 辅助：空态 → 显式生成 → 结论优先 → 依据联动组件
    await page.getByTestId('side-tab-ai').click()
    await expect(page.getByTestId('ai-empty')).toContainText('尚未生成')
    await page.getByTestId('ai-generate').click()
    await expect(page.getByTestId('ai-review')).toContainText('快速解读结论')
    await expect(page.getByTestId('ai-perspective-spatial_pattern')).toContainText('高值体元集中')
    await expect(page.getByTestId('ai-decision-options')).toContainText('维持当前模型')
    await expect(page.getByTestId('ai-identity')).toContainText('deepseek-chat')
    await expect(page.getByTestId('ai-identity')).toContainText('ai_review.v1')
    await page.getByTestId('ai-evidence-spatial_pattern').click()
    await page.getByTestId('ai-ref-spatial_pattern-component-1').click()
    await expect
      .poll(async () =>
        (await frameMessages())
          .filter((m) => m.type === 'FOCUS_ANNOTATION')
          .map((m) => m.annotationId)
          .at(-1),
      )
      .toBe('component-1')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: `${EVIDENCE_DIR}/04-ai-review.png` })

    // 页面无水平溢出（1920×1080 一屏演示）
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
  })
})

// v0.9.0：答辩模式状态。章节固定、可导航、可退出；store 只持有模式与
// 章节索引，不 fetch 数据、不启动服务。镜头书签只承载元数据，场景未
// 就绪前章节切换绝不强行移镜。
import { computed, reactive } from 'vue'

export type PresentationChapterId =
  | 'overview'
  | 'resistivity'
  | 'microseismic'
  | 'gas'
  | 'custom-data'
  | 'innovation-boundaries'

export interface PresentationChapter {
  id: PresentationChapterId
  title: string
  subtitle: string
}

export const PRESENTATION_CHAPTERS: readonly PresentationChapter[] = [
  { id: 'overview', title: '平台能力总览', subtitle: '数据 → 建模 → 验证 → 成果 → 证据' },
  { id: 'resistivity', title: '地下电阻率', subtitle: '数据 — 模型 — 三维成果 — 关键发现' },
  { id: 'microseismic', title: '微震速度', subtitle: '测线结构 — 空间验证 — 速度场' },
  { id: 'gas', title: '煤层瓦斯含量', subtitle: '稀疏数据 — 解释性建模 — 分层与覆盖 — 限制' },
  { id: 'custom-data', title: '自定义数据', subtitle: '载入演示文件，走通同一建模链' },
  { id: 'innovation-boundaries', title: '创新点与已知边界', subtitle: '证据链 · 失败语义 · 能力边界' },
] as const

interface PresentationState {
  active: boolean
  chapterIndex: number
}

const state = reactive<PresentationState>({
  active: false,
  chapterIndex: 0,
})

const active = computed(() => state.active)
const currentIndex = computed(() => state.chapterIndex)
const currentId = computed(() => PRESENTATION_CHAPTERS[state.chapterIndex].id)
const currentChapter = computed(() => PRESENTATION_CHAPTERS[state.chapterIndex])
const isFirst = computed(() => state.chapterIndex <= 0)
const isLast = computed(() => state.chapterIndex >= PRESENTATION_CHAPTERS.length - 1)

export function usePresentationStore() {
  return {
    active,
    currentIndex,
    currentId,
    currentChapter,
    isFirst,
    isLast,
    chapters: PRESENTATION_CHAPTERS,
    enter() {
      state.active = true
      state.chapterIndex = 0
    },
    exit() {
      state.active = false
    },
    goTo(id: string) {
      const index = PRESENTATION_CHAPTERS.findIndex((c) => c.id === id)
      if (index < 0) return
      state.chapterIndex = index
    },
    next() {
      if (!isLast.value) state.chapterIndex += 1
    },
    prev() {
      if (!isFirst.value) state.chapterIndex -= 1
    },
  }
}

// 测试辅助：重置单例状态
export function resetPresentationStore() {
  state.active = false
  state.chapterIndex = 0
}

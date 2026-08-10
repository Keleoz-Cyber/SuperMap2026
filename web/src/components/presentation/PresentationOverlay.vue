<script setup lang="ts">
// v0.9.0：答辩模式控制层。章节标题/位置/上一节/下一节/章节目录/退出 +
// 服务状态徽标（全局头隐藏后由本层保留服务可见性）；
// 只读导航，不承载任何编辑或危险操作。
import { Close, ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { usePresentationStore } from '../../stores/presentation'

withDefaults(defineProps<{
  serviceOnline?: boolean | null
}>(), { serviceOnline: null })

const store = usePresentationStore()
</script>

<template>
  <div class="presentation-overlay" data-test="presentation-overlay">
    <div class="overlay-top">
      <div class="chapter-info">
        <h1 class="chapter-title" data-test="presentation-title">{{ store.currentChapter.value.title }}</h1>
        <span class="chapter-subtitle">{{ store.currentChapter.value.subtitle }}</span>
      </div>
      <div class="overlay-controls">
        <span
          class="service-state"
          :class="{ offline: serviceOnline === false }"
          data-test="presentation-service-status"
          role="status"
        >
          <span class="dot" :class="serviceOnline === false ? 'bad' : serviceOnline === null ? 'pending' : 'ok'" />
          {{ serviceOnline === null ? '服务检测中' : serviceOnline ? '服务在线' : '服务离线' }}
        </span>
        <span class="position mono" data-test="presentation-position">
          {{ store.currentIndex.value + 1 }} / {{ store.chapters.length }}
        </span>
        <button
          type="button"
          class="overlay-btn"
          data-test="presentation-prev"
          aria-label="上一节"
          :disabled="store.isFirst.value"
          @click="store.prev()"
        >
          <el-icon :size="16"><ArrowLeft /></el-icon>
        </button>
        <button
          type="button"
          class="overlay-btn"
          data-test="presentation-next"
          aria-label="下一节"
          :disabled="store.isLast.value"
          @click="store.next()"
        >
          <el-icon :size="16"><ArrowRight /></el-icon>
        </button>
        <button
          type="button"
          class="overlay-btn exit"
          data-test="presentation-exit"
          aria-label="退出答辩模式"
          @click="store.exit()"
        >
          <el-icon :size="16"><Close /></el-icon>
        </button>
      </div>
    </div>

    <nav class="chapter-dots" aria-label="章节目录">
      <button
        v-for="(chapter, i) in store.chapters"
        :key="chapter.id"
        type="button"
        class="chapter-dot"
        :class="{ active: i === store.currentIndex.value }"
        :data-test="`presentation-chapter-${chapter.id}`"
        :aria-label="`第 ${i + 1} 节：${chapter.title}`"
        :aria-current="i === store.currentIndex.value ? 'true' : undefined"
        @click="store.goTo(chapter.id)"
      >
        <span class="dot-marker" aria-hidden="true" />
        <span class="dot-label">{{ chapter.title }}</span>
      </button>
    </nav>
  </div>
</template>

<style scoped>
.presentation-overlay {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  padding: var(--s1-space-4) var(--s1-space-6);
  border-bottom: 1px solid var(--s1-border-soft);
  background: var(--s1-surface-glass);
  backdrop-filter: blur(10px);
  /* 答辩章节导航必须恒可见：吸顶（答辩全屏下全局头已隐藏，顶部即视口顶） */
  position: sticky;
  top: 0;
  z-index: 40;
}

.overlay-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s1-space-4);
}

.chapter-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.chapter-title {
  margin: 0;
  font-size: var(--s1-font-2xl);
  font-weight: 700;
  color: var(--s1-text-strong);
}

.chapter-subtitle {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  letter-spacing: 0.04em;
}

.overlay-controls {
  display: flex;
  align-items: center;
  gap: var(--s1-space-2);
}

.service-state {
  display: inline-flex;
  align-items: center;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  border: 1px solid var(--s1-border);
  border-radius: 999px;
  padding: 3px 10px;
  margin-right: 6px;
  white-space: nowrap;
}

.service-state.offline {
  color: var(--s1-warning);
  border-color: rgba(217, 168, 78, 0.4);
}

.position {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  margin-right: 6px;
}

.overlay-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--s1-radius-sm);
  border: 1px solid var(--s1-border);
  background: var(--s1-surface-2);
  color: var(--s1-text-dim);
  cursor: pointer;
  transition:
    color var(--s1-motion-fast) var(--s1-ease-out),
    border-color var(--s1-motion-fast) var(--s1-ease-out);
}

.overlay-btn:hover:not(:disabled) {
  color: var(--s1-cyan-strong);
  border-color: var(--s1-cyan-dim);
}

.overlay-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.overlay-btn.exit:hover {
  color: var(--s1-error);
  border-color: var(--s1-error);
}

.chapter-dots {
  display: flex;
  gap: var(--s1-space-2);
  flex-wrap: wrap;
}

.chapter-dot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--s1-text-faint);
  font-size: var(--s1-font-sm);
  padding: 3px 10px;
  cursor: pointer;
  transition:
    color var(--s1-motion-fast) var(--s1-ease-out),
    background var(--s1-motion-fast) var(--s1-ease-out);
}

.chapter-dot:hover {
  color: var(--s1-cyan-strong);
}

.chapter-dot.active {
  color: var(--s1-gold);
  background: var(--s1-gold-ghost);
  border-color: var(--s1-gold-dim);
}

.dot-marker {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
</style>

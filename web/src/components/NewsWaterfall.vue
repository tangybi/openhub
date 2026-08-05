<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { NewsItem } from '../types'
import NewsCard from './NewsCard.vue'

const props = defineProps<{ items: NewsItem[]; loading: boolean; finished: boolean }>()
const emit = defineEmits<{
  (e: 'load-more'): void
  (e: 'open', item: NewsItem): void
}>()

// 固定单列居中展示。用 flex 列替代 CSS multicol：
// multicol 里给子项加 transform（hover 上移）会让部分列的卡片在个别浏览器上整卡消失，
// 这是 fragment + transform 的渲染 bug；flex 列布局不经过 fragment，transform 安全。
const columns = computed(() => [props.items])

const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) emit('load-more')
    },
    { rootMargin: '500px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
})
</script>

<template>
  <div class="waterfall">
    <div class="waterfall-columns">
      <div v-for="(col, ci) in columns" :key="ci" class="waterfall-col">
        <div v-for="it in col" :key="it.id" class="waterfall-cell">
          <NewsCard :item="it" @open="$emit('open', it)" />
        </div>
      </div>
    </div>

    <div ref="sentinel" class="waterfall-sentinel">
      <span v-if="loading" class="sentinel-text">加载中…</span>
      <span v-else-if="finished" class="sentinel-text">已加载全部 {{ items.length }} 条</span>
    </div>

    <div v-if="!loading && items.length === 0" class="empty">
      <p>暂无热点数据</p>
      <p class="empty-sub">
        后端启动后点右上角「抓取最新」拉取 RSS，或在 app/ 目录执行
        <code>uv run python -m app.services.rss_ingest</code>
      </p>
    </div>
  </div>
</template>

<style scoped>
.waterfall-columns {
  display: flex;
  justify-content: center;
}

.waterfall-col {
  width: 100%;
  max-width: 720px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.waterfall-sentinel {
  text-align: center;
  padding: 16px 0;
}

.sentinel-text {
  font-size: 13px;
  color: var(--on-dark-3);
}

.empty {
  text-align: center;
  padding: 80px 0;
  color: var(--on-dark-2);
}

.empty p {
  margin: 6px 0;
}

.empty-sub {
  font-size: 13px;
  color: var(--on-dark-3);
}
</style>

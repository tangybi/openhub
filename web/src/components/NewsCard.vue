<script setup lang="ts">
import { computed } from 'vue'
import type { NewsItem } from '../types'
import { timeAgo } from '../utils/format'

const props = defineProps<{ item: NewsItem }>()
const emit = defineEmits<{ (e: 'open', item: NewsItem): void }>()

const hotLevel = computed(() => {
  if (props.item.hot_score >= 80) return 'high'
  if (props.item.hot_score >= 60) return 'mid'
  return 'low'
})
</script>

<template>
  <article class="card" @click="emit('open', item)">
    <div class="card-body">
      <div class="card-tags">
        <span class="card-cat">{{ item.category }}</span>
        <span class="card-hot" :class="hotLevel">🔥 {{ item.hot_score }}</span>
      </div>
      <h3 class="card-title">{{ item.title }}</h3>
      <p class="card-summary">{{ item.summary }}</p>
      <div class="card-foot">
        <span class="card-source">{{ item.source }}</span>
        <span class="card-time">{{ item.published_at ? timeAgo(item.published_at) : '' }}</span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.card {
  background: var(--surface);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: transform 0.18s, box-shadow 0.18s;
  display: flex;
  flex-direction: column;
}

.card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}

.card-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-cat {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-warm);
  background: var(--accent-soft);
  padding: 3px 8px;
  border-radius: 999px;
}

.card-hot {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 999px;
  color: #fff;
}

.card-hot.high {
  background: rgba(239, 68, 68, 0.85);
}

.card-hot.mid {
  background: rgba(245, 158, 11, 0.85);
}

.card-hot.low {
  background: rgba(107, 114, 128, 0.7);
}

.card-body {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-title {
  margin: 0;
  font-size: 15px;
  line-height: 1.4;
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 2px;
}

.card-source {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-warm);
}

.card-time {
  font-size: 12px;
  color: var(--text-3);
}
</style>

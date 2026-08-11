<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { CategoryInfo, NewsItem } from '../types'
import { fetchCategories, fetchNews, triggerIngest } from '../api'
import CategoryFilter from '../components/CategoryFilter.vue'
import NewsWaterfall from '../components/NewsWaterfall.vue'
import AskAgent from '../components/AskAgent.vue'

const categories = ref<CategoryInfo[]>([])
const activeCategory = ref('全部')
const search = ref('')
const items = ref<NewsItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
// 初始为 true：避免子组件 IntersectionObserver 在首次加载前抢先触发 loadMore
// （空页面时 sentinel 立即可见，会把页码推进到 2 导致初始加载被 loading 守卫跳过）
const loading = ref(true)
const initialized = ref(false)
const finished = ref(false)
const ingesting = ref(false)
const ingestMsg = ref('')

const detail = ref<NewsItem | null>(null)

async function load(reset = false) {
  // reset（切换分类/搜索/首次加载）永远执行；追加加载才受 loading 守卫限制
  if (loading.value && !reset) return
  loading.value = true
  if (reset) {
    page.value = 1
    items.value = []
    finished.value = false
  }
  try {
    const data = await fetchNews({
      category: activeCategory.value,
      q: search.value,
      page: page.value,
      page_size: pageSize,
    })
    items.value = reset ? data.items : [...items.value, ...data.items]
    total.value = data.total
    finished.value = items.value.length >= data.total
    if (reset) initialized.value = true
  } catch (e: any) {
    // 空态会提示启动后端
    console.error(e)
  } finally {
    loading.value = false
  }
}

function loadMore() {
  if (!initialized.value || finished.value || loading.value) return
  page.value++
  load()
}

function onCategory(c: string) {
  activeCategory.value = c
  load(true)
}

function onSearch() {
  load(true)
}

function onClearSearch() {
  search.value = ''
  load(true)
}

async function onIngest() {
  if (ingesting.value) return
  ingesting.value = true
  ingestMsg.value = '抓取中（RSS → DeepSeek 摘要）…'
  try {
    const stats = await triggerIngest()
    ingestMsg.value = `抓取完成：新增 ${stats.new} 条，共 ${stats.total} 条`
    await load(true)
  } catch (e: any) {
    ingestMsg.value = `抓取失败：${e?.message || '未知错误'}`
  } finally {
    ingesting.value = false
    setTimeout(() => (ingestMsg.value = ''), 5000)
  }
}

onMounted(async () => {
  try {
    categories.value = await fetchCategories()
  } catch {
    categories.value = [{ name: '全部', count: 0 }]
  }
  load(true)
})
</script>

<template>
  <div class="news-view">
    <div class="news-toolbar">
      <CategoryFilter :categories="categories" :active="activeCategory" @select="onCategory" />
      <div class="toolbar-right">
        <div class="search-box">
          <input
            v-model="search"
            placeholder="搜索标题 / 来源"
            @keyup.enter="onSearch"
          />
          <button v-if="search" class="search-clear" @click="onClearSearch">×</button>
          <button class="search-btn" @click="onSearch">搜索</button>
        </div>
        <button class="ingest-btn" :disabled="ingesting" @click="onIngest">
          {{ ingesting ? '抓取中…' : '⚡ 抓取最新' }}
        </button>
      </div>
    </div>
    <p v-if="ingestMsg" class="ingest-msg">{{ ingestMsg }}</p>

    <div class="news-summary">
      共 {{ total }} 条热点 · {{ activeCategory }}
    </div>

    <div class="news-layout" :class="{ 'has-detail': !!detail }">
      <div class="news-list">
        <NewsWaterfall
          :items="items"
          :loading="loading"
          :finished="finished"
          @load-more="loadMore"
          @open="detail = $event"
        />
      </div>

      <!-- 详情分屏：右栏 60% -->
      <transition name="fade">
        <aside v-if="detail" class="detail-pane">
          <div class="detail-head">
            <span class="detail-cat">{{ detail.category }}</span>
            <button class="detail-close" aria-label="关闭详情" @click="detail = null">×</button>
          </div>
          <h2 class="detail-title">{{ detail.title }}</h2>
          <p class="detail-summary">{{ detail.summary }}</p>
          <div class="detail-meta">
            <span>来源 {{ detail.source }}</span>
            <span v-if="detail.published_at">{{ detail.published_at.replace('T', ' ').slice(0, 16) }}</span>
            <span>🔥 {{ detail.hot_score }}</span>
          </div>
          <a class="detail-link" :href="detail.url" target="_blank" rel="noopener">
            查看原文 ↗
          </a>
        </aside>
      </transition>
    </div>

    <AskAgent agent-label="AI 助手" />
  </div>
</template>

<style scoped>
.news-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.news-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;

  /* 滚动时吸顶，固定在 sticky 头部导航（63px）下方 */
  position: sticky;
  top: 63px;
  z-index: 40;
  padding: 10px 0;
  background: rgba(233, 233, 240, 0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--surface);
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 999px;
  overflow: hidden;
  position: relative;
}

.search-box:focus-within {
  border-color: var(--accent);
}

.search-box input {
  padding: 8px 30px 8px 14px;
  border: none;
  outline: none;
  font-size: 13px;
  width: 190px;
  background: transparent;
  color: var(--on-dark);
}

.search-box input::placeholder {
  color: var(--on-dark-3);
}

.search-clear {
  position: absolute;
  right: 78px;
  color: var(--on-dark-2);
  font-size: 15px;
}

.search-btn {
  padding: 8px 14px;
  background: var(--grad);
  color: var(--accent-strong);
  font-size: 13px;
  font-weight: 600;
  border-radius: 0 999px 999px 0;
}

.ingest-btn {
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.1);
  font-size: 13px;
  font-weight: 500;
  color: var(--on-dark);
  transition: all 0.18s;
}

.ingest-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--on-dark);
}

.ingest-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ingest-msg {
  margin: 0;
  font-size: 13px;
  color: var(--on-dark-2);
}

.news-summary {
  font-size: 13px;
  color: var(--on-dark-3);
}

.news-layout {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
  align-items: start;
}

/* 左 30% : 右 60% ≈ 1:2 */
.news-layout.has-detail {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
}

.news-list {
  min-width: 0;
}

.detail-pane {
  position: sticky;
  top: 140px;
  max-height: calc(100vh - 160px);
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px 22px;
}

.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.detail-cat {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-warm);
  background: var(--accent-soft);
  padding: 4px 10px;
  border-radius: 999px;
}

.detail-close {
  font-size: 22px;
  color: var(--text-3);
  line-height: 1;
}

.detail-close:hover {
  color: var(--text);
}

.detail-title {
  margin: 14px 0 10px;
  font-size: 18px;
  line-height: 1.45;
}

.detail-summary {
  margin: 0 0 16px;
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-2);
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 16px;
}

.detail-link {
  display: inline-block;
  padding: 10px 18px;
  border-radius: 999px;
  background: var(--grad);
  color: var(--accent-strong);
  font-size: 14px;
  font-weight: 600;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 900px) {
  .news-layout.has-detail {
    grid-template-columns: 1fr;
  }

  .detail-pane {
    position: static;
    max-height: none;
  }
}
</style>

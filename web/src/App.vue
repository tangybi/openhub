<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { AgentInfo } from './types'
import { fetchAgents } from './api'
import { runWithSpan } from './utils/tracing'
import { AGENT_TABS } from './agents'
import AppHeader from './components/AppHeader.vue'
import NewsView from './views/NewsView.vue'
import PasteView from './views/PasteView.vue'
import DashboardView from './views/DashboardView.vue'
import PlaceholderView from './views/PlaceholderView.vue'

const agents = ref<AgentInfo[]>([])
// 看板固定 tab：不来自后端 agents 列表，独立渲染在 agent tabs 之后
const DASHBOARD_TAB = { name: 'dashboard', label: '看板', icon: '📊' }
const activeAgent = ref('news')
const backendUp = ref(true)

const activeAgentInfo = computed(() => agents.value.find((a) => a.name === activeAgent.value))

onMounted(async () => {
  // 页面浏览埋点：整段首屏初始化作为一次 page_view 业务事件（含 fetchAgents 耗时）
  await runWithSpan('page_view', { page: 'home', agent: activeAgent.value }, async () => {
    try {
      agents.value = await fetchAgents()
    } catch {
      // 后端不可用时退化为本地定义，保证 UI 可展示
      backendUp.value = false
      agents.value = AGENT_TABS.map((t) => ({
        name: t.name,
        label: t.label,
        category: t.label,
        available: true,
        description: '',
      }))
    }
  })
})
</script>

<template>
  <div class="app">
    <AppHeader
      :agents="agents"
      :active="activeAgent"
      :extra-tab="DASHBOARD_TAB"
      @select="activeAgent = $event"
    />
    <div v-if="!backendUp" class="offline-banner">
      ⚠️ 后端未连接（请先启动 <code>uv run uvicorn main:app --port 8000</code>），当前展示本地兜底数据。
    </div>
    <main class="app-main">
      <NewsView v-if="activeAgent === 'news'" />
      <PasteView v-else-if="activeAgent === 'paste'" />
      <DashboardView v-else-if="activeAgent === 'dashboard'" />
      <PlaceholderView v-else :agent="activeAgentInfo" />
    </main>
  </div>
</template>

<style scoped>
.offline-banner {
  background: #fef3c7;
  color: #92400e;
  font-size: 13px;
  text-align: center;
  padding: 8px 16px;
}
</style>

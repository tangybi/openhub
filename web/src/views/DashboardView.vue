<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ErrorDetailTable from '../components/ErrorDetailTable.vue'
import type { DashboardStats, EndpointStat } from '../types'
import { fetchDashboardStats } from '../api'

const stats = ref<DashboardStats | null>(null)
const loading = ref(true)
const error = ref('')
const showErrors = ref(false) // 「异常」卡片点击弹窗

const PRESETS = [
  { label: '今天', days: 1 },
  { label: '近3天', days: 3 },
  { label: '近7天', days: 7 },
  { label: '近30天', days: 30 },
]
const days = ref(7)

const fmtMs = (v: number | null) => (v == null ? '—' : `${v.toFixed(1)} ms`)
const fmtInt = (v: number) => (v >= 1000 ? v.toLocaleString() : String(v))
const fmtTokens = (v: number) =>
  v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v / 1_000).toFixed(1)}K` : String(v)

async function load() {
  loading.value = true
  error.value = ''
  try {
    stats.value = await fetchDashboardStats({ days: days.value, include_errors: true })
  } catch (e: any) {
    stats.value = null
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function onPreset(n: number) {
  days.value = n
  load()
}

// 端点表 p95 列纯 CSS 条：width = p95 / maxP95 * 100%
const maxP95 = computed(() =>
  Math.max(0, ...(stats.value?.endpoints ?? []).map((e) => e.p95_latency_ms ?? 0)),
)
const p95Bar = (e: EndpointStat) =>
  maxP95.value > 0 ? `${Math.max(4, ((e.p95_latency_ms ?? 0) / maxP95.value) * 100)}%` : '4%'

// 异常弹窗：点击遮罩、关闭按钮、Esc 均可关闭；打开时锁住背景滚动。
function openErrors() {
  if (stats.value && stats.value.overview.error_count > 0) showErrors.value = true
}
function closeErrors() {
  showErrors.value = false
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') closeErrors()
}
watch(showErrors, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="dashboard">
    <div class="dash-toolbar">
      <div class="presets">
        <button
          v-for="p in PRESETS"
          :key="p.days"
          class="preset"
          :class="{ active: days === p.days }"
          @click="onPreset(p.days)"
        >
          {{ p.label }}
        </button>
      </div>
      <div class="toolbar-right">
        <span v-if="stats" class="range">
          {{ stats.range.start }} ~ {{ stats.range.end }} · 解析 {{ stats.files_parsed.length }} 个日志文件
        </span>
        <button class="refresh" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '🔄 刷新' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="error">⚠️ {{ error }}</p>

    <!-- 加载中骨架 -->
    <div v-if="loading" class="loading">
      <div class="skeleton cards" />
      <div class="skeleton table" />
    </div>

    <template v-else-if="stats">
      <!-- 空态：日志里没有任何前端 page_view -->
      <div v-if="stats.overview.pv === 0" class="empty">
        <div class="empty-icon">📭</div>
        <h3>该时段暂无数据</h3>
        <p>
          {{ stats.range.start }} ~ {{ stats.range.end }} 没有可统计的日志。
          <template v-if="stats.overview.uv_source === 'device_id'">
            已有前端埋点（device_id）在运行，请确认后端日志目录有该时段的
            <code>app_YYYYMMDD.log</code>。
          </template>
          <template v-else>
            若刚上线埋点，UV 从有 <code>device_id</code> 的新日志开始统计；旧日志回退用去重用户 token。
          </template>
        </p>
      </div>

      <template v-else>
        <!-- 概览卡片 -->
        <div class="cards">
          <div class="card">
            <div class="card-label">UV（去重设备）</div>
            <div class="card-value">{{ fmtInt(stats.overview.uv) }}</div>
            <div class="card-sub">
              <span class="src-badge" :class="`src-${stats.overview.uv_source}`">
                {{ stats.overview.uv_source === 'device_id' ? '设备号' : stats.overview.uv_source === 'user_token' ? '用户 token' : '无来源' }}
              </span>
              <span>用户数 {{ fmtInt(stats.overview.user_count) }}</span>
            </div>
          </div>
          <div class="card">
            <div class="card-label">PV（页面浏览）</div>
            <div class="card-value">{{ fmtInt(stats.overview.pv) }}</div>
            <div class="card-sub">提问 {{ fmtInt(stats.overview.ask_count) }} 次</div>
          </div>
          <div class="card">
            <div class="card-label">接口请求</div>
            <div class="card-value">{{ fmtInt(stats.overview.total_requests) }}</div>
            <div class="card-sub">平均 {{ fmtMs(stats.overview.avg_latency_ms) }}</div>
          </div>
          <div class="card">
            <div class="card-label">Token 用量（LLM + 向量）</div>
            <div class="card-value accent">{{ fmtTokens(stats.overview.total_tokens) }}</div>
            <div class="card-sub stack">
              <span>LLM {{ fmtInt(stats.overview.llm_calls) }} 次 · 输入 {{ fmtTokens(stats.overview.prompt_tokens) }} / 输出 {{ fmtTokens(stats.overview.completion_tokens) }}</span>
              <span v-if="stats.overview.embed_tokens">向量化 {{ fmtTokens(stats.overview.embed_tokens) }}</span>
            </div>
          </div>
          <div class="card">
            <div class="card-label">P95 响应时长</div>
            <div class="card-value accent">{{ fmtMs(stats.overview.p95_latency_ms) }}</div>
            <div class="card-sub">最快路径均值，最长 {{ fmtMs(stats.overview.max_latency_ms) }}</div>
          </div>
          <div
            class="card"
            :class="{ clickable: stats.overview.error_count > 0 }"
            :role="stats.overview.error_count > 0 ? 'button' : undefined"
            :tabindex="stats.overview.error_count > 0 ? 0 : undefined"
            @click="openErrors"
            @keydown.enter="openErrors"
          >
            <div class="card-label">异常</div>
            <div class="card-value" :class="stats.overview.error_count > 0 ? 'danger' : 'ok'">
              {{ fmtInt(stats.overview.error_count) }}
            </div>
            <div class="card-sub">
              后端 + 前端
              <span v-if="stats.overview.error_count > 0" class="view-hint">点击查看详情 →</span>
            </div>
          </div>
          <div class="card">
            <div class="card-label">错误率（后端）</div>
            <div class="card-value" :class="stats.overview.error_rate > 0 ? 'danger' : 'ok'">
              {{ stats.overview.error_rate.toFixed(1) }}%
            </div>
            <div class="card-sub">错误数 / 接口请求</div>
          </div>
        </div>

        <!-- 端点响应时长表 -->
        <section class="panel">
          <h3 class="panel-title">接口响应时长（按端点）</h3>
          <table class="tbl">
            <thead>
              <tr>
                <th>Method</th>
                <th>Route</th>
                <th class="num">请求数</th>
                <th class="num">avg</th>
                <th class="num">p95</th>
                <th class="num">max</th>
                <th class="num">错误</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in stats.endpoints" :key="`${e.method} ${e.route}`">
                <td><span class="method" :class="`m-${e.method.toLowerCase()}`">{{ e.method }}</span></td>
                <td class="route">{{ e.route }}</td>
                <td class="num">{{ fmtInt(e.count) }}</td>
                <td class="num">{{ fmtMs(e.avg_latency_ms) }}</td>
                <td class="num">
                  <div class="p95-cell">
                    <div class="p95-bar" :style="{ width: p95Bar(e) }" />
                    <span>{{ fmtMs(e.p95_latency_ms) }}</span>
                  </div>
                </td>
                <td class="num">{{ fmtMs(e.max_latency_ms) }}</td>
                <td class="num">
                  <span v-if="e.error_count" class="err-count">{{ e.error_count }}</span>
                  <span v-else class="muted">0</span>
                </td>
              </tr>
              <tr v-if="!stats.endpoints.length">
                <td colspan="7" class="muted center">该时段无接口请求日志</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- 异常详情表 -->
        <section class="panel">
          <h3 class="panel-title">异常报错详情（最近 {{ stats.errors.length }} 条）</h3>
          <ErrorDetailTable :errors="stats.errors" />
        </section>
      </template>
    </template>
  </div>

  <!-- 异常详情弹窗 -->
  <Teleport to="body">
    <div v-if="showErrors" class="modal-mask" @click.self="closeErrors">
      <div class="modal" role="dialog" aria-modal="true" aria-label="异常详情">
        <header class="modal-head">
          <h3>异常详情（{{ stats?.errors.length ?? 0 }} 条）</h3>
          <button class="modal-close" aria-label="关闭" @click="closeErrors">✕</button>
        </header>
        <div class="modal-body">
          <ErrorDetailTable v-if="stats" :errors="stats.errors" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dash-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.presets {
  display: flex;
  gap: 6px;
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.08);
  padding: 4px;
  border-radius: 12px;
}

.preset {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--on-dark-2);
  transition: all 0.18s;
}

.preset:hover {
  color: var(--on-dark);
}

.preset.active {
  background: var(--accent);
  color: var(--accent-strong);
  font-weight: 600;
  box-shadow: var(--shadow);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.range {
  font-size: 12px;
  color: var(--on-dark-3);
}

.refresh {
  padding: 7px 14px;
  border-radius: 999px;
  background: var(--grad);
  color: var(--accent-strong);
  font-size: 13px;
  font-weight: 600;
}

.refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  margin: 0;
  padding: 10px 16px;
  border-radius: var(--radius-sm);
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
  font-size: 13px;
}

.loading {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.skeleton {
  background: linear-gradient(90deg, rgba(0, 0, 0, 0.04), rgba(0, 0, 0, 0.08), rgba(0, 0, 0, 0.04));
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border-radius: var(--radius);
}

.skeleton.cards {
  height: 96px;
}

.skeleton.table {
  height: 240px;
}

@keyframes shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}

.empty {
  text-align: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 64px 32px;
  box-shadow: var(--shadow);
}

.empty-icon {
  font-size: 40px;
}

.empty h3 {
  margin: 12px 0 8px;
}

.empty p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
  max-width: 560px;
  margin-inline: auto;
}

.empty code {
  font-size: 12px;
  background: var(--accent-soft);
  padding: 1px 6px;
  border-radius: 6px;
}

/* 概览卡片 */
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 18px 20px;
}

.card-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 6px;
}

.card-value {
  font-size: 28px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.card-value.accent {
  color: var(--accent);
}

.card-value.danger {
  color: #b91c1c;
}

.card-value.ok {
  color: #15803d;
}

.card-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-2);
}

.card-sub.stack {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

/* 面板 / 表格 */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 18px 20px;
  overflow-x: auto;
}

.panel-title {
  margin: 0 0 14px;
  font-size: 14px;
  font-weight: 600;
}

.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tbl th {
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.tbl td {
  padding: 9px 10px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  vertical-align: top;
}

.tbl tr:last-child td {
  border-bottom: none;
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.center {
  text-align: center;
}

.muted {
  color: var(--text-3);
}

.route {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  word-break: break-all;
  min-width: 200px;
}

.method {
  display: inline-block;
  min-width: 52px;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 6px;
  margin-right: 6px;
}

.m-get {
  background: rgba(37, 99, 235, 0.12);
  color: #1d4ed8;
}

.m-post {
  background: rgba(22, 163, 74, 0.12);
  color: #15803d;
}

.m-put {
  background: rgba(217, 119, 6, 0.12);
  color: #b45309;
}

.m-delete {
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
}

/* p95 条 */
.p95-cell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.p95-bar {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  height: 8px;
  border-radius: 999px;
  background: var(--accent-2);
  opacity: 0.5;
}

.p95-cell span {
  position: relative;
  z-index: 1;
  background: var(--surface);
  padding: 0 4px;
}

.err-count {
  display: inline-block;
  min-width: 22px;
  text-align: center;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
}

/* UV 卡片的来源徽章（错误表的样式在 ErrorDetailTable.vue） */
.src-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.src-device_id {
  background: var(--accent-soft);
  color: var(--accent-warm);
}

.src-user_token {
  background: rgba(37, 99, 235, 0.1);
  color: #1d4ed8;
}

.src-none {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-3);
}

/* 「异常」卡片可点击提示 */
.view-hint {
  color: var(--accent);
  font-weight: 600;
}

.card.clickable {
  cursor: pointer;
  transition: box-shadow 0.18s, transform 0.18s, border-color 0.18s;
}

.card.clickable:hover {
  box-shadow: var(--shadow-lg);
  border-color: var(--accent-2);
  transform: translateY(-1px);
}

.card.clickable:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* 异常详情弹窗 */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 20, 30, 0.45);
  animation: fade-in 0.15s ease;
}

.modal {
  display: flex;
  flex-direction: column;
  max-width: 960px;
  width: 100%;
  max-height: min(80vh, 720px);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  animation: pop-in 0.18s ease;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.modal-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.modal-close {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  font-size: 14px;
  line-height: 1;
  color: var(--text-2);
  transition: background 0.15s, color 0.15s;
}

.modal-close:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text);
}

.modal-body {
  padding: 16px 20px 20px;
  overflow: auto;
}

@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes pop-in {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (max-width: 720px) {
  .dash-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>

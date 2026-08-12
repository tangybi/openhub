<script setup lang="ts">
// 异常详情表：面板与「异常」卡片的弹窗共用同一份渲染。
import type { ErrorDetail } from '../types'

defineProps<{ errors: ErrorDetail[] }>()

const statusClass = (code: number | null) => {
  if (code == null) return 'chip-neutral'
  if (code >= 500) return 'chip-red'
  if (code >= 400) return 'chip-amber'
  return 'chip-neutral'
}
</script>

<template>
  <table v-if="errors.length" class="tbl err-tbl">
    <thead>
      <tr>
        <th>时间</th>
        <th>来源</th>
        <th>端点</th>
        <th>状态</th>
        <th>请求 / 响应</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="er in errors" :key="er.trace_id">
        <td class="time">{{ er.time }}</td>
        <td>
          <span class="src-badge" :class="er.source === 'backend' ? 'src-backend' : 'src-frontend'">
            {{ er.source === 'backend' ? '后端' : '前端' }}
          </span>
        </td>
        <td class="route">
          <div v-if="er.source === 'backend'">
            <span class="method" :class="`m-${(er.method || 'get').toLowerCase()}`">{{ er.method }}</span>
            {{ er.route }}
          </div>
          <div v-else class="muted">{{ er.route || er.message }}</div>
        </td>
        <td>
          <span class="chip" :class="statusClass(er.status_code)">
            {{ (er.status_code ?? er.span_status) || '—' }}
          </span>
        </td>
        <td class="body-cell">
          <code v-if="er.source === 'backend'" class="body">
            <template v-if="er.request_body">
              <span class="k">req</span> {{ er.request_body }}
            </template>
            <template v-if="er.request_body && er.response_body">
              <br />
            </template>
            <template v-if="er.response_body">
              <span class="k">resp</span> {{ er.response_body }}
            </template>
          </code>
          <code v-else class="body">{{ er.message }}</code>
          <div class="trace" :title="er.trace_id">trace {{ er.trace_id.slice(0, 8) }}</div>
        </td>
      </tr>
    </tbody>
  </table>
  <p v-else class="muted center pad">该时段无异常 🎉</p>
</template>

<style scoped>
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

.time {
  font-size: 12px;
  white-space: nowrap;
  color: var(--text-2);
}

.src-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.src-backend {
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
}

.src-frontend {
  background: rgba(37, 99, 235, 0.1);
  color: #1d4ed8;
}

.chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.chip-red {
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
}

.chip-amber {
  background: rgba(217, 119, 6, 0.14);
  color: #b45309;
}

.chip-neutral {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-3);
}

.body-cell {
  min-width: 260px;
}

.body {
  display: block;
  max-height: 96px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 11px;
  line-height: 1.6;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}

.body .k {
  color: var(--text-3);
  font-weight: 700;
}

.trace {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-3);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.pad {
  padding: 24px 0;
}
</style>

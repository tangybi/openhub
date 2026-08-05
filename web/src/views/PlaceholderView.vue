<script setup lang="ts">
import type { AgentInfo } from '../types'

defineProps<{ agent: AgentInfo | undefined }>()
</script>

<template>
  <div class="placeholder">
    <div class="placeholder-card">
      <div class="placeholder-icon">🚧</div>
      <h2>{{ agent?.label ?? 'Agent' }}</h2>
      <p>{{ agent?.description ?? '该 Agent 正在规划中。' }}</p>
      <span class="badge">即将上线</span>
    </div>
  </div>
</template>

<style scoped>
.placeholder {
  display: grid;
  place-items: center;
  padding: 80px 0;
}

.placeholder-card {
  text-align: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 48px 64px;
  box-shadow: var(--shadow);
}

.placeholder-icon {
  font-size: 40px;
}

.placeholder-card h2 {
  margin: 12px 0 8px;
}

.placeholder-card p {
  margin: 0 0 16px;
  color: var(--text-2);
  font-size: 14px;
}

.badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-warm);
  background: var(--accent-soft);
  padding: 5px 12px;
  border-radius: 999px;
}
</style>

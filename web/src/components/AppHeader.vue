<script setup lang="ts">
import type { AgentInfo } from '../types'
import { agentIcon } from '../agents'

defineProps<{ agents: AgentInfo[]; active: string }>()
defineEmits<{ (e: 'select', name: string): void }>()
</script>

<template>
  <header class="header">
    <div class="header-inner">
      <div class="brand">
        <div class="brand-mark">HS</div>
        <div class="brand-text">
          <div class="brand-name">HotScope</div>
          <div class="brand-sub">热点聚合 · 多 Agent</div>
        </div>
      </div>
      <nav class="tabs">
        <button
          v-for="a in agents"
          :key="a.name"
          class="tab"
          :class="{ active: a.name === active }"
          @click="$emit('select', a.name)"
        >
          <span class="tab-icon">{{ agentIcon(a.name) }}</span>
          {{ a.label }}
          <span v-if="!a.available" class="soon">规划中</span>
        </button>
      </nav>
    </div>
  </header>
</template>

<style scoped>
.header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(233, 233, 240, 0.85);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.header-inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: var(--grad);
  color: var(--accent-strong);
  font-weight: 800;
  font-size: 16px;
  display: grid;
  place-items: center;
  box-shadow: 0 4px 12px rgba(30, 30, 30, 0.25);
}

.brand-name {
  font-weight: 700;
  font-size: 17px;
  line-height: 1.1;
  color: var(--on-dark);
}

.brand-sub {
  font-size: 12px;
  color: var(--on-dark-2);
}

.tabs {
  display: flex;
  gap: 6px;
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.08);
  padding: 4px;
  border-radius: 14px;
}

.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  color: var(--on-dark-2);
  transition: all 0.18s;
  position: relative;
}

.tab:hover {
  color: var(--on-dark);
}

.tab.active {
  background: var(--accent);
  color: var(--accent-strong);
  box-shadow: var(--shadow);
  font-weight: 600;
}

.tab-icon {
  font-size: 15px;
}

.soon {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.06);
  color: var(--on-dark-2);
  border: 1px solid rgba(0, 0, 0, 0.1);
}

@media (max-width: 640px) {
  .header-inner {
    justify-content: center;
  }
}
</style>

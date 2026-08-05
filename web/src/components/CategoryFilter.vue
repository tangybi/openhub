<script setup lang="ts">
import type { CategoryInfo } from '../types'

defineProps<{ categories: CategoryInfo[]; active: string }>()
defineEmits<{ (e: 'select', name: string): void }>()
</script>

<template>
  <div class="cat-filter">
    <button
      v-for="c in categories"
      :key="c.name"
      class="cat"
      :class="{ active: c.name === active }"
      @click="$emit('select', c.name)"
    >
      {{ c.name }}
      <span class="cat-count">{{ c.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.cat-filter {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cat {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  color: var(--on-dark-2);
  background: rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0, 0, 0, 0.1);
  transition: all 0.18s;
}

.cat:hover {
  border-color: var(--accent);
  color: var(--on-dark);
}

.cat.active {
  background: var(--grad);
  color: var(--accent-strong);
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(30, 30, 30, 0.25);
}

.cat-count {
  font-size: 11px;
  opacity: 0.75;
}
</style>

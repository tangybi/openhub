<script setup lang="ts">
import { nextTick, ref } from 'vue'
import type { ChatMessage } from '../types'
import { askAgent } from '../api'

const props = defineProps<{ agentLabel: string }>()

const open = ref(false)
const input = ref('')
const sending = ref(false)
const messages = ref<ChatMessage[]>([])
const bodyRef = ref<HTMLElement | null>(null)

async function scrollBottom() {
  await nextTick()
  if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
}

async function send() {
  const q = input.value.trim()
  if (!q || sending.value) return
  messages.value.push({ role: 'user', content: q })
  input.value = ''
  sending.value = true
  scrollBottom()
  try {
    const res = await askAgent('news', q)
    messages.value.push({ role: 'assistant', content: res.answer, sources: res.sources })
  } catch (e: any) {
    messages.value.push({ role: 'assistant', content: e?.message || '请求失败', error: true })
  } finally {
    sending.value = false
    scrollBottom()
  }
}
</script>

<template>
  <div class="ask">
    <transition name="pop">
      <div v-if="open" class="ask-panel">
        <div class="ask-head">
          <span>向「{{ agentLabel }}」提问</span>
          <button class="ask-close" @click="open = false" aria-label="关闭">×</button>
        </div>
        <div ref="bodyRef" class="ask-body">
          <div v-if="!messages.length" class="ask-empty">
            输入问题，Agent 会基于当前聚合的热点新闻回答并附来源。
          </div>
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="msg-bubble" :class="{ error: m.error }">{{ m.content }}</div>
            <div v-if="m.sources?.length" class="msg-sources">
              <a v-for="s in m.sources" :key="s.url" :href="s.url" target="_blank" rel="noopener">
                ↗ {{ s.source }} · {{ s.title }}
              </a>
            </div>
          </div>
          <div v-if="sending" class="msg assistant">
            <div class="msg-bubble thinking">思考中…</div>
          </div>
        </div>
        <div class="ask-input">
          <input
            v-model="input"
            placeholder="问点什么…"
            :disabled="sending"
            @keyup.enter="send"
          />
          <button class="ask-send" :disabled="sending || !input.trim()" @click="send">发送</button>
        </div>
      </div>
    </transition>
    <button class="ask-fab" @click="open = !open">💬 问 Agent</button>
  </div>
</template>

<style scoped>
.ask {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 80;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}

.ask-fab {
  padding: 12px 20px;
  border-radius: 999px;
  background: var(--grad);
  color: var(--accent-strong);
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 8px 24px rgba(30, 30, 30, 0.25);
  transition: transform 0.18s, box-shadow 0.18s;
}

.ask-fab:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(30, 30, 30, 0.32);
}

.ask-panel {
  width: 380px;
  max-width: calc(100vw - 40px);
  height: 520px;
  max-height: calc(100vh - 120px);
  background: var(--surface);
  border-radius: 20px;
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ask-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid var(--border);
}

.ask-close {
  font-size: 20px;
  line-height: 1;
  color: var(--text-3);
}

.ask-close:hover {
  color: var(--text);
}

.ask-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--bg);
}

.ask-empty {
  margin: auto;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
  max-width: 240px;
  line-height: 1.6;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.msg.user {
  align-items: flex-end;
}

.msg.assistant {
  align-items: flex-start;
}

.msg-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 13.5px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.msg.user .msg-bubble {
  background: var(--grad);
  color: var(--accent-strong);
  border-bottom-right-radius: 4px;
}

.msg.assistant .msg-bubble {
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  box-shadow: var(--shadow);
}

.msg-bubble.error {
  color: #dc2626;
}

.msg-bubble.thinking {
  color: var(--text-3);
}

.msg-sources {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 85%;
}

.msg-sources a {
  font-size: 12px;
  color: var(--accent-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-sources a:hover {
  text-decoration: underline;
}

.ask-input {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
}

.ask-input input {
  flex: 1;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 14px;
  outline: none;
}

.ask-input input:focus {
  border-color: var(--accent);
}

.ask-send {
  padding: 0 18px;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-strong);
  font-size: 14px;
  font-weight: 600;
}

.ask-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pop-enter-active,
.pop-leave-active {
  transition: opacity 0.18s, transform 0.18s;
}

.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.98);
}
</style>

<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import type { ChatMessage } from '../types'
import { askRouterStream, fetchChatHistory } from '../api'

const props = defineProps<{ agentLabel: string }>()

const open = ref(false)
const input = ref('')
const sending = ref(false)
const messages = ref<ChatMessage[]>([])
const bodyRef = ref<HTMLElement | null>(null)
const historyLoaded = ref(false)

// 自动滚到底部：nextTick 等 Vue 把增量渲染进 DOM，rAF 再等浏览器布局完成，
// 双保险避免流式增量时差一帧没滚到位；即时跳转，流式场景不用平滑动画。
function scrollBottom() {
  const el = bodyRef.value
  if (!el) return
  nextTick(() => requestAnimationFrame(() => { el.scrollTop = el.scrollHeight }))
}

// 兜底：任何消息变化（发送/流式增量/来源/错误标注/历史恢复）都自动滚底。
// flush:'post' 保证回调在 DOM 更新后跑，此时 scrollHeight 才是最新高度。
watch(messages, scrollBottom, { deep: true, flush: 'post' })

// 打开聊天窗时自动滚到底部：重开面板（已有消息）也能断点续看最新内容。
// flush:'post' 关键：回调在 v-if 面板渲染进 DOM 之后才执行，此时 bodyRef 已挂载，
// scrollBottom 才不会因取到 null 而空跑。再叠加历史恢复分支：
// 仅当本地还没有消息时拉取一次（刷新/重开断点恢复）。
watch(
  open,
  async (v) => {
    if (!v) return
    scrollBottom()
    if (!historyLoaded.value && !messages.value.length) {
      try {
        const history = await fetchChatHistory()
        if (history.length) {
          messages.value = history.map((m) => ({ role: m.role, content: m.content }))
          scrollBottom()
        }
      } catch {
        // 历史拉取失败不阻塞，继续允许提问
      }
      historyLoaded.value = true
    }
  },
  { flush: 'post' },
)

async function send() {
  const q = input.value.trim()
  if (!q || sending.value) return
  messages.value.push({ role: 'user', content: q })
  input.value = ''
  sending.value = true
  scrollBottom()
  // 先插入空 assistant 气泡，流式累积；持有对象引用，避免按索引在并发/关闭面板时漂移。
  // 必须用 reactive() 包裹：否则 onDelta 改的是原始对象，而模板读的是响应式代理，
  // 增量不会触发重渲染，整段答案要等 sending 置 false 才一次性出现（=无流式效果）。
  const bubble = reactive<ChatMessage>({ role: 'assistant', content: '' })
  messages.value.push(bubble)
  await askRouterStream(q, {
    onSources(sources) {
      bubble.sources = sources
    },
    onDelta(text) {
      bubble.content += text
      scrollBottom()
    },
    onDone() {
      // 结束：无需额外处理
    },
    onError(msg) {
      if (!bubble.content) {
        bubble.content = msg
      } else {
        bubble.content += `\n\n[${msg}]`
      }
      bubble.error = true
      scrollBottom()
    },
  })
  sending.value = false
  scrollBottom()
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
            输入问题，自动派发给对应专家（热点 / 粘贴查询…）。
          </div>
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="msg-bubble" :class="{ error: m.error }">
              <template v-if="m.content">{{ m.content }}</template>
              <span v-else-if="sending && i === messages.length - 1" class="thinking">思考中…</span>
            </div>
            <div v-if="m.sources?.length" class="msg-sources">
              <a v-for="s in m.sources" :key="s.url" :href="s.url" target="_blank" rel="noopener">
                ↗ {{ s.source }} · {{ s.title }}
              </a>
            </div>
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
  color: var(--accent-warm);
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

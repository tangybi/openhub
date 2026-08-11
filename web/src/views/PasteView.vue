<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createPaste, deletePaste, fetchPasteDetail } from '../api'
import type { PasteCreateResponse, PasteDetailResponse, PasteLink } from '../types'

// ---------- 创建表单 ----------
const title = ref('')
const language = ref('')
const content = ref('')
const expiresIn = ref(0)
const fileInput = ref<HTMLInputElement | null>(null)

// 已选附件。用 {uid, file} 包裹：uid 保证 v-for key 唯一（同名同大小的文件也各自独立展示），
// 文件对象原样保留用于 FormData 上传。
interface PickedFile {
  uid: string
  file: File
}
let fileSeq = 0
const selectedFiles = ref<PickedFile[]>([])
const sending = ref(false)
const createError = ref('')
const result = ref<PasteCreateResponse | null>(null)
const copiedId = ref('')

// ---------- 最近创建（localStorage 管理） ----------
interface RecentPaste {
  code: string
  title: string
  delete_token: string
  created_at: string
  links: PasteLink[]
}
const RECENT_KEY = 'paste_recent_v1'
const recent = ref<RecentPaste[]>([])
const showToken = ref(false)

// ---------- 按 code 查看 ----------
const viewCode = ref('')
const viewing = ref(false)
const viewError = ref('')
const detail = ref<PasteDetailResponse | null>(null)

const EXPIRES = [
  { label: '永不过期', value: 0 },
  { label: '1 小时', value: 3600 },
  { label: '1 天', value: 86400 },
  { label: '7 天', value: 604800 },
  { label: '30 天', value: 2592000 },
  { label: '1 年', value: 31536000 },
]
const LANGUAGES = [
  'text', 'plain', 'python', 'javascript', 'typescript', 'html', 'css',
  'json', 'bash', 'sql', 'go', 'rust', 'java', 'markdown',
]

function loadRecent() {
  try {
    const arr = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    // 兼容旧版本：只有 short_url 没有 links 的项，回填成单条「正文」短链
    recent.value = (Array.isArray(arr) ? arr : [])
      .filter((x: any) => x && x.code)
      .map((x: any): RecentPaste => ({
        code: x.code,
        title: x.title || x.code,
        delete_token: x.delete_token,
        created_at: x.created_at,
        links:
          Array.isArray(x.links) && x.links.length
            ? x.links
            : x.short_url
              ? [{ id: 'content', name: '正文', url: x.short_url }]
              : [],
      }))
  } catch {
    recent.value = []
  }
}
function saveRecent() {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent.value.slice(0, 10)))
  } catch {
    /* 隐私模式等写失败忽略 */
  }
}
function pushRecent(r: PasteCreateResponse) {
  recent.value.unshift({
    code: r.code,
    title: title.value.trim() || r.code,
    delete_token: r.delete_token,
    created_at: new Date().toISOString(),
    links: r.links,
  })
  saveRecent()
}
function removeRecent(code: string) {
  recent.value = recent.value.filter((r) => r.code !== code)
  saveRecent()
}

onMounted(loadRecent)

function onFileChange(e: Event) {
  const el = e.target as HTMLInputElement
  const picked = Array.from(el.files ?? [])
  // 累加选择：同一输入框多次打开对话框都保留，避免「后选覆盖先选」导致只传上一个文件。
  // 按 名称+大小+最后修改时间 去重，防止重复选同一文件。
  const seen = new Set(selectedFiles.value.map((p) => `${p.file.name}|${p.file.size}|${p.file.lastModified}`))
  for (const f of picked) {
    const key = `${f.name}|${f.size}|${f.lastModified}`
    if (!seen.has(key)) {
      seen.add(key)
      selectedFiles.value.push({ uid: `f-${fileSeq++}`, file: f })
    }
  }
  el.value = '' // 清空 input，便于再次选择同一文件时能触发 change
}
function removeFile(uid: string) {
  selectedFiles.value = selectedFiles.value.filter((p) => p.uid !== uid)
}

async function doCreate() {
  createError.value = ''
  result.value = null
  if (!content.value.trim() && !selectedFiles.value.length) {
    createError.value = '正文与附件不能同时为空'
    return
  }
  sending.value = true
  try {
    const r = await createPaste({
      title: title.value.trim(),
      language: language.value.trim(),
      content: content.value,
      expires_in: expiresIn.value,
      files: selectedFiles.value.map((p) => p.file),
    })
    result.value = r
    pushRecent(r)
    copiedId.value = ''
    // 清空表单，便于继续创建下一条
    content.value = ''
    selectedFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
  } catch (e: any) {
    createError.value = e?.message || '创建失败'
  } finally {
    sending.value = false
  }
}

async function copyText(text: string, id = '') {
  try {
    await navigator.clipboard.writeText(text)
    copiedId.value = id
    setTimeout(() => (copiedId.value = ''), 1500)
  } catch {
    window.prompt('复制链接（按 Ctrl+C）', text) // 剪贴板不可用时降级
  }
}

async function doDelete(code: string, token: string) {
  if (!window.confirm(`确认删除粘贴 ${code}？删除后短链将失效。`)) return
  try {
    await deletePaste(code, token)
    removeRecent(code)
    if (result.value?.code === code) result.value = null
    if (detail.value?.code === code) detail.value = null
  } catch (e: any) {
    window.alert(e?.message || '删除失败')
  }
}

async function doView() {
  const code = viewCode.value.trim()
  if (!code) return
  viewing.value = true
  viewError.value = ''
  detail.value = null
  try {
    detail.value = await fetchPasteDetail(code)
  } catch (e: any) {
    viewError.value = e?.message || '查询失败'
  } finally {
    viewing.value = false
  }
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
function fmtTime(iso: string | null): string {
  if (!iso) return '永不过期'
  const d = new Date(iso)
  return d.toLocaleString()
}
</script>

<template>
  <div class="paste-view">
    <div class="paste-hero">
      <h1>📋 粘贴</h1>
      <p>创建粘贴，分享短链；也可凭 code 查看或删除已保存内容。</p>
    </div>

    <!-- 创建卡片 -->
    <section class="card">
      <h2 class="card-title">创建</h2>
      <div class="form-grid">
        <label class="field">
          <span>标题（可选）</span>
          <input v-model="title" type="text" placeholder="粘贴标题" maxlength="200" />
        </label>
        <label class="field">
          <span>语言</span>
          <input v-model="language" list="paste-langs" placeholder="text" maxlength="32" />
          <datalist id="paste-langs">
            <option v-for="l in LANGUAGES" :key="l" :value="l" />
          </datalist>
        </label>
        <label class="field">
          <span>过期时间</span>
          <select v-model="expiresIn">
            <option v-for="e in EXPIRES" :key="e.value" :value="e.value">{{ e.label }}</option>
          </select>
        </label>
      </div>
      <label class="field">
        <span>正文</span>
        <textarea
          v-model="content"
          rows="8"
          placeholder="粘贴正文（纯文本，1MB 上限）"
          spellcheck="false"
        ></textarea>
      </label>
      <label class="field">
        <span>附件（可选，最多 10 个 / 单个 10MB / 总 20MB，可多选）</span>
        <input ref="fileInput" type="file" multiple @change="onFileChange" />
        <div v-if="selectedFiles.length" class="file-list">
          <span v-for="p in selectedFiles" :key="p.uid" class="file-tag">
            📎 {{ p.file.name }}（{{ fmtBytes(p.file.size) }}）
            <button
              type="button"
              class="file-remove"
              title="移除"
              @click.stop.prevent="removeFile(p.uid)"
            >×</button>
          </span>
        </div>
      </label>
      <p v-if="createError" class="error">{{ createError }}</p>
      <button class="btn-primary" :disabled="sending" @click="doCreate">
        {{ sending ? '创建中…' : '创建粘贴' }}
      </button>
    </section>

    <!-- 结果卡片 -->
    <section v-if="result" class="card success-card">
      <h2 class="card-title">✅ 创建成功</h2>
      <div class="result-row">
        <span class="result-label">短链</span>
        <span class="link-list result-value">
          <span v-for="link in result.links" :key="link.id" class="link-chip">
            <span class="link-name">{{ link.name }}</span>
            <code class="link-url">{{ link.url }}</code>
            <button class="btn-ghost" @click="copyText(link.url, link.id)">
              {{ copiedId === link.id ? '已复制 ✓' : '复制' }}
            </button>
            <a class="btn-ghost" :href="link.url" target="_blank" rel="noopener">打开 ↗</a>
          </span>
        </span>
      </div>
      <div class="result-row">
        <span class="result-label">code</span>
        <code class="result-value">{{ result.code }}</code>
        <button class="btn-ghost" @click="copyText(result.code, 'code')">复制</button>
      </div>
      <div class="result-row">
        <span class="result-label">过期</span>
        <span class="result-value">{{ fmtTime(result.expires_at) }}</span>
      </div>
      <div v-if="result.files.length" class="result-row">
        <span class="result-label">附件</span>
        <span class="file-list result-value">
          <a
            v-for="f in result.files"
            :key="f.name + f.url"
            :href="f.url"
            target="_blank"
            rel="noopener"
            class="file-tag file-link"
          >
            📎 {{ f.name }}（{{ fmtBytes(f.size) }}）↗
          </a>
        </span>
      </div>
      <div class="result-row">
        <span class="result-label">删除凭证</span>
        <code v-if="showToken" class="result-value">{{ result.delete_token }}</code>
        <span v-else class="result-value dim">••••••••</span>
        <button class="btn-ghost" @click="showToken = !showToken">{{ showToken ? '隐藏' : '显示' }}</button>
        <button v-if="showToken" class="btn-ghost" @click="copyText(result.delete_token, 'token')">复制</button>
      </div>
      <div class="result-actions">
        <button class="btn-danger" @click="doDelete(result.code, result.delete_token)">删除</button>
      </div>
    </section>

    <!-- 最近创建 -->
    <section v-if="recent.length" class="card">
      <h2 class="card-title">最近创建</h2>
      <ul class="recent-list">
        <li v-for="r in recent" :key="r.code" class="recent-item">
          <div class="recent-main">
            <span class="recent-title">{{ r.title }}</span>
            <span class="link-list recent-links">
              <span v-for="link in r.links" :key="link.id" class="link-chip">
                <span class="link-name">{{ link.name }}</span>
                <code class="link-url">{{ link.url }}</code>
                <button class="btn-ghost" @click="copyText(link.url, link.id)">
                  {{ copiedId === link.id ? '已复制' : '复制' }}
                </button>
              </span>
            </span>
          </div>
          <div class="recent-actions">
            <button class="btn-danger-sm" @click="doDelete(r.code, r.delete_token)">删除</button>
          </div>
        </li>
      </ul>
    </section>

    <!-- 按 code 查看 -->
    <section class="card">
      <h2 class="card-title">按 code 查看</h2>
      <div class="view-row">
        <input v-model="viewCode" class="view-input" placeholder="输入粘贴 code，如 v9pugUnU" @keyup.enter="doView" />
        <button class="btn-primary" :disabled="viewing || !viewCode.trim()" @click="doView">
          {{ viewing ? '查询中…' : '查看' }}
        </button>
      </div>
      <p v-if="viewError" class="error">{{ viewError }}</p>
      <div v-if="detail" class="detail">
        <div class="detail-meta">
          <span>code: <code>{{ detail.code }}</code></span>
          <span>浏览 {{ detail.view_count }}</span>
          <span>创建于 {{ fmtTime(detail.created_at) }}</span>
          <span>过期 {{ fmtTime(detail.expires_at) }}</span>
        </div>
        <div v-if="detail.links.length" class="detail-links">
          <span class="result-label">短链</span>
          <span class="link-list">
            <span v-for="link in detail.links" :key="link.id" class="link-chip">
              <span class="link-name">{{ link.name }}</span>
              <code class="link-url">{{ link.url }}</code>
              <button class="btn-ghost" @click="copyText(link.url, link.id)">
                {{ copiedId === link.id ? '已复制 ✓' : '复制' }}
              </button>
              <a class="btn-ghost" :href="link.url" target="_blank" rel="noopener">打开 ↗</a>
            </span>
          </span>
        </div>
        <pre v-if="detail.content" class="detail-content">{{ detail.content }}</pre>
        <p v-if="detail.files.length" class="detail-files">
          <a
            v-for="f in detail.files"
            :key="f.name + f.url"
            :href="f.url"
            target="_blank"
            rel="noopener"
            class="file-tag file-link"
          >
            📎 {{ f.name }}（{{ fmtBytes(f.size) }}）↗
          </a>
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.paste-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 760px;
  margin: 0 auto;
  padding: 20px 0;
}

.paste-hero h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.paste-hero p {
  margin: 0;
  color: var(--text-2);
  font-size: 13.5px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  box-shadow: var(--shadow);
}
.card-title {
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 600;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 560px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--text-2);
}
.field input,
.field select,
.field textarea {
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: inherit;
  background: var(--bg-soft);
  outline: none;
}
.field textarea {
  resize: vertical;
  font-family: var(--font-mono, monospace);
  line-height: 1.6;
}
.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: var(--accent);
}

.file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.file-tag {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-warm);
}
.file-link {
  text-decoration: none;
  display: inline-block;
}
.file-link:hover {
  text-decoration: underline;
}
.file-remove {
  margin-left: 2px;
  padding: 0 4px;
  line-height: 1.2;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-3);
  font-size: 14px;
  cursor: pointer;
}
.file-remove:hover {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.08);
}

.link-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.link-chip {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-soft);
  font-size: 12.5px;
}
.link-chip .link-name {
  color: var(--text-3);
  font-size: 12px;
}
.link-chip .link-url {
  font-size: 12px;
  color: var(--accent-warm);
  word-break: break-all;
}
.link-chip .btn-ghost {
  padding: 2px 8px;
  font-size: 12px;
}

.recent-links {
  gap: 4px;
  margin-top: 2px;
}
.detail-links {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 13.5px;
}
.detail-links .link-list {
  flex: 1;
}

.error {
  color: #dc2626;
  font-size: 13px;
  margin: 6px 0 0;
}

.btn-primary {
  padding: 10px 22px;
  border-radius: 999px;
  background: var(--grad);
  color: var(--accent-strong);
  font-size: 14px;
  font-weight: 600;
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-ghost {
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  border: 1px solid var(--border);
  color: var(--accent-warm);
  background: var(--bg-soft);
  text-decoration: none;
  cursor: pointer;
}
.btn-ghost:hover {
  border-color: var(--accent);
}

.btn-danger {
  padding: 8px 18px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: #dc2626;
}
.btn-danger-sm {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #dc2626;
  border: 1px solid #f3c6c6;
  background: #fff;
  cursor: pointer;
}

.success-card {
  border-color: rgba(22, 163, 74, 0.4);
}
.result-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  font-size: 13.5px;
  flex-wrap: wrap;
}
.result-label {
  width: 64px;
  color: var(--text-3);
  font-size: 12.5px;
  flex-shrink: 0;
}
.result-value {
  word-break: break-all;
  flex: 1;
}
.result-value.dim {
  color: var(--text-3);
}
.result-actions {
  margin-top: 10px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}

.recent-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.recent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-soft);
}
.recent-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.recent-title {
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.recent-code {
  font-size: 12px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.recent-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.view-row {
  display: flex;
  gap: 8px;
}
.view-input {
  flex: 1;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: var(--font-mono, monospace);
  background: var(--bg-soft);
  outline: none;
}
.view-input:focus {
  border-color: var(--accent);
}

.detail {
  margin-top: 12px;
}
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12.5px;
  color: var(--text-2);
  margin-bottom: 10px;
}
.detail-content {
  margin: 0 0 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 360px;
  overflow-y: auto;
}
.detail-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
}
</style>

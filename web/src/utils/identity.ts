// 设备唯一标识 + 会话 id：localStorage 持久化，随请求头 `X-Device-Id` / `X-Session-Id` 传给后端。
// device_id 首次访问生成后长期不变；session_id 可调用 newSession() 开启新会话。

const DEVICE_KEY = 'hotscope.device_id'
const SESSION_KEY = 'hotscope.session_id'

function getOrCreate(key: string): string {
  let v = localStorage.getItem(key)
  if (!v) {
    v = crypto.randomUUID()
    localStorage.setItem(key, v)
  }
  return v
}

export function getDeviceId(): string {
  return getOrCreate(DEVICE_KEY)
}

export function getSessionId(): string {
  return getOrCreate(SESSION_KEY)
}

/** 开启新会话（清空历史上下文），返回新 session_id。 */
export function newSession(): string {
  const s = crypto.randomUUID()
  localStorage.setItem(SESSION_KEY, s)
  return s
}

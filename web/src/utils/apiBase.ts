// 生产环境后端域名：web/.env.production 里配 VITE_API_BASE_URL（或 Vercel 环境变量）。
// 本地开发留空 → 走 vite.config.ts 的 /api 代理（127.0.0.1:8000）。
// api.ts（请求）与 tracing.ts（埋点上报）共用，避免循环依赖。
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 生产环境后端 API 域名（如 https://api.example.com）；本地开发留空走 vite 代理 */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

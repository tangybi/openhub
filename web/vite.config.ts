import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // 开发环境把 /api 代理到本地 FastAPI（uv run uvicorn main:app --port 8000）
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 手动指定文件名格式，包含内容哈希
        entryFileNames: 'assets/js/[name]-[hash].js',
        chunkFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          // CSS 文件也加上哈希
          if (assetInfo.names.includes('.css')) {
            return 'assets/css/[name]-[hash].[ext]';
          }
          return 'assets/[name]-[hash].[ext]';
        },
      },
    },
  },
})

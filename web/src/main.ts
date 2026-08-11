import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { initTracing } from './utils/tracing'

// 初始化前端埋点（须在任何 span 创建前调用）
initTracing()
createApp(App).mount('#app')

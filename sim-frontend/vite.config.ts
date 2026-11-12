import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// 隔离验收端口：默认仍指向 8000，只有显式设置 env 时才改目标。
const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'
const wsTarget = process.env.VITE_WS_TARGET || 'ws://127.0.0.1:8000'

export default defineConfig({
  // Disposable test instances must not load the user's frontend .env files.
  envDir: process.env.FINAL_DELEGATION_RUN || undefined,
  plugins: [
    vue(),
    process.env.TRACE_BUILD === '1' && {
      name: 'trace-build-transform',
      transform(_code: string, id: string) {
        if (
          !id.includes('node_modules') ||
          id.includes('element-plus') ||
          id.includes('vue-router') ||
          id.includes('/pinia/') ||
          id.includes('/vue/')
        ) {
          console.log(`[trace-build] ${id}`)
        }
        return null
      },
    },
  ].filter(Boolean),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api/v1/ws': { target: wsTarget, ws: true },
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': { target: wsTarget, ws: true }
    },
    watch: {
      // Windows 上避免监视器撞上编辑器/工具的临时文件（EBUSY 崩溃导致 dev server 反复掉线）
      ignored: ['**/node_modules/**', '**/.git/**', '**/*.tmp', '**/*.tmpdir/**', '**/.*.tmp*'],
    },
  },
  build: {
    minify: 'esbuild',
    cssMinify: true,
    reportCompressedSize: true,
    rollupOptions: {
      output: {
        // 按真实模块路径分组：应用全部通过 `element-plus/es/components/...` 子路径按需
        // 引入，桶入口 `element-plus` 根本不在依赖图里，旧的 `element: ['element-plus']`
        // 写法等于没生效（P2-24）。
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'element'
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('xterm')) return 'xterm'
          if (id.includes('/vue/') || id.includes('vue-router') || id.includes('pinia') || id.includes('@vue/')) {
            return 'vendor'
          }
          return undefined
        },
      },
    },
  }
})

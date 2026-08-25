import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
  server: {
    port: 8002,
    strictPort: true,
    // WSL から /mnt/c（Windows 側）を見る構成では inotify が届かないためポーリングで検知する
    watch: { usePolling: true, interval: 300 },
  },
  build: {
    // main.ts がトップレベル await を使う（地図を作る前に meta.json を解決するため）
    target: 'es2022',
  },
  define: {
    __BUILD_TIME__: JSON.stringify(
      new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC',
    ),
  },
})

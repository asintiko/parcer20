import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'

const pkg = JSON.parse(readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8')) as { version: string }

// Design sandbox: standalone browser-only build, no Electron, no /api proxy.
export default defineConfig({
    plugins: [react()],
    base: '/',
    define: {
        __APP_VERSION__: JSON.stringify(pkg.version),
    },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    build: {
        assetsDir: 'assets',
        rollupOptions: {
            output: {
                entryFileNames: 'assets/[name]-[hash].js',
                chunkFileNames: 'assets/[name]-[hash].js',
                assetFileNames: 'assets/[name]-[hash].[ext]',
            },
        },
    },
    server: {
        port: 5180,
        strictPort: false,
        host: '127.0.0.1',
        fs: {
            allow: ['..'],
            strict: false,
        },
    },
    publicDir: 'public',
})

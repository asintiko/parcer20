import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import pkg from './package.json' with { type: 'json' }

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    // Use relative paths for Electron file:// protocol
    base: './',
    define: {
        __APP_VERSION__: JSON.stringify(pkg.version),
    },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    build: {
        // Ensure assets use relative paths
        assetsDir: 'assets',
        rollupOptions: {
            output: {
                // Consistent naming for caching
                entryFileNames: 'assets/[name]-[hash].js',
                chunkFileNames: 'assets/[name]-[hash].js',
                assetFileNames: 'assets/[name]-[hash].[ext]',
                // Split heavy vendors out of the startup chunk. ExcelJS is
                // dynamically imported at its call site and only loads for export.
                manualChunks: {
                    'vendor-react': ['react', 'react-dom', 'react-router-dom'],
                    'vendor-mui': ['@mui/material', '@mui/x-date-pickers', '@emotion/react', '@emotion/styled'],
                    'vendor-tanstack': [
                        '@tanstack/react-query',
                        '@tanstack/react-query-persist-client',
                        '@tanstack/query-sync-storage-persister',
                        '@tanstack/react-table',
                        '@tanstack/react-virtual',
                    ],
                    'vendor-markdown': ['react-markdown', 'rehype-raw', 'rehype-sanitize', 'remark-gfm'],
                    'vendor-motion': ['motion'],
                    'vendor-exceljs': ['exceljs'],
                },
            }
        }
    },
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
        fs: {
            // Allow serving files from parent directories
            allow: ['..'],
            strict: false
        }
    },
    publicDir: 'public',
})

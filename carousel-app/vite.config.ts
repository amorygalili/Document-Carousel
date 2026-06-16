import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // Use relative paths so the Python tool can prepend a <base> tag
  // pointing at the HTTP server and all assets resolve correctly.
  base: './',
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  server: {
    host: true
  },
  preview: {
    allowedHosts: ['host.docker.internal']
  }
})

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files go to dist/ and are served by api/main.py: index.html at "/", bundles at "/static/".
// `npm run dev` proxies API calls to the Radar server (default http://127.0.0.1:8000).
const api = process.env.RADAR_API ?? "http://127.0.0.1:8000";
const proxied = ["/auth", "/watch", "/strategy", "/content", "/discover", "/health"];

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "dist",
    assetsDir: "assets",
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(proxied.map((p) => [p, { target: api, changeOrigin: false }])),
  },
  test: { environment: "jsdom", globals: false },
} as never);

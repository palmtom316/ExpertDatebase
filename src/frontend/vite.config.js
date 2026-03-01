import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: process.env.EXPERTDB_DEV_API_BASE || "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});

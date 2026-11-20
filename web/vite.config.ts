/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

/**
 * HTTPS for testing on phones: when PUBLIC_WEB_URL in api/.env starts with https://,
 * the dev server uses a self-signed certificate. Phones show a warning once; after
 * "proceed", the camera works (browsers only allow it on https or localhost).
 */
function wantsHttps(): boolean {
  try {
    const env = readFileSync(new URL("../api/.env", import.meta.url), "utf8");
    return /^PUBLIC_WEB_URL\s*=\s*https:\/\//m.test(env);
  } catch {
    return false;
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), ...(wantsHttps() ? [basicSsl({ name: "vms-dev" })] : [])],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    host: true,
    // Names that point at this computer's Wi-Fi address, e.g. 192.168.1.12.sslip.io: WhatsApp
    // only turns named addresses into links, not bare IP addresses.
    allowedHosts: [".sslip.io", ".nip.io"],
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: false },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Keep visitor/guard bundles free of admin-only code (route-level lazy chunks).
        manualChunks: { react: ["react", "react-dom", "react-router"] },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright
  },
});

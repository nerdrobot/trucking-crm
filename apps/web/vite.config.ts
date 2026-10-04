import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const apiOrigin = env.VITE_API_BASE_URL
    ? new URL(env.VITE_API_BASE_URL).origin
    : "";
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    `connect-src 'self' ${apiOrigin}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
  return {
    plugins: [
      react(),
      {
        name: "production-security-headers",
        generateBundle() {
          this.emitFile({
            type: "asset",
            fileName: "_headers",
            source: `/*\n  Content-Security-Policy: ${policy}\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n  X-Frame-Options: DENY\n`,
          });
        },
      },
    ],
    server: {
      proxy: {
        "/api": "http://127.0.0.1:8787",
        "/health": "http://127.0.0.1:8787",
      },
    },
    test: {
      include: ["src/**/*.test.{ts,tsx}"],
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
      coverage: {
        include: ["src/**/*.{ts,tsx}"],
        exclude: [
          "src/**/*.test.{ts,tsx}",
          "src/test-setup.ts",
          "src/main.tsx",
        ],
        thresholds: { lines: 80, statements: 80, branches: 80 },
      },
    },
  };
});

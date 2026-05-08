import { defineConfig, Plugin, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendTarget = env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

  return {
  server: {
    host: "::",
    port: 8080,
    fs: {
      allow: ["./client", "./shared"],
      deny: [".env", ".env.*", "*.{crt,pem}", "**/.git/**", "server/**"],
    },
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/dashboard": { target: backendTarget, changeOrigin: true },
      "/inventory": { target: backendTarget, changeOrigin: true },
      "/staff": { target: backendTarget, changeOrigin: true },
      "/users": { target: backendTarget, changeOrigin: true },
      "/timesheets": { target: backendTarget, changeOrigin: true },
      "/sage": { target: backendTarget, changeOrigin: true },
      "/chat": { target: backendTarget, changeOrigin: true },
      "/analytics": { target: backendTarget, changeOrigin: true },
      "/intelligence": { target: backendTarget, changeOrigin: true },
      "/reports": { target: backendTarget, changeOrigin: true },
      "/workflow": { target: backendTarget, changeOrigin: true },
      "/audit": { target: backendTarget, changeOrigin: true },
      "/stock": { target: backendTarget, changeOrigin: true },
      "/hr": { target: backendTarget, changeOrigin: true },
      "/ops": { target: backendTarget, changeOrigin: true },
      "/crm": { target: backendTarget, changeOrigin: true },
      "/procurement": { target: backendTarget, changeOrigin: true, ws: true },
      "/auth": { target: backendTarget, changeOrigin: true },
      "/token": { target: backendTarget, changeOrigin: true },
      "/refresh": { target: backendTarget, changeOrigin: true },
      "/logout": { target: backendTarget, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist/spa",
  },
  plugins: [react(), ...(command === "serve" ? [expressPlugin()] : [])],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./client"),
      "@shared": path.resolve(__dirname, "./shared"),
    },
  },
  test: {
    // Run in node environment by default (no DOM needed for existing spec files).
    // Switch individual files to "jsdom" via `@vitest-environment jsdom` docblock
    // when writing React component tests.
    environment: "node",
    include: [
      "client/**/*.{test,spec}.{ts,tsx}",
      "server/**/*.{test,spec}.ts",
      "shared/**/*.{test,spec}.ts",
    ],
    globals: true,
  },
};
});

function expressPlugin(): Plugin {
  return {
    name: "express-plugin",
    apply: "serve", // Only apply during development (serve mode)
    async configureServer(server) {
      // Lazy-load Express server only in dev — dynamic path prevents esbuild
      // from attempting to resolve this module during the Docker/production build.
      const serverPath = "./server";
      const { createServer } = await import(serverPath);
      const app = createServer();

      // Add Express app as middleware to Vite dev server
      server.middlewares.use(app);
    },
  };
}

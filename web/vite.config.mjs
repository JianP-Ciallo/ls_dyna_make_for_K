import { fileURLToPath } from "node:url";

// Development serves the same source as the Python production server.
export default {
  root: fileURLToPath(new URL("../lsprepost_mcp/web/static", import.meta.url)),
  publicDir: false,
  cacheDir: fileURLToPath(new URL("./node_modules/.vite", import.meta.url)),
  resolve: {
    alias: { three: fileURLToPath(new URL("../lsprepost_mcp/web/static/vendor/three/three.module.min.js", import.meta.url)) },
  },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
};

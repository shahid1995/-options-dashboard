import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

// Minimal vitest config for component tests:
// - The project follows the Next.js convention of JSX inside `.js` files
//   (e.g. app/paper/PortfolioAnalyticsPanel.js), which Vitest/Vite does not
//   parse by default — raise the esbuild loader for .js/.jsx to "jsx".
// - Components import via the jsconfig "@/*" alias; mirror it for tests.
export default defineConfig({
  esbuild: {
    loader: "jsx",
    include: /\.(js|jsx)$/,
    exclude: [],
    // The project's components rely on Next.js's JSX transform (automatic
    // runtime, no `import React`), so match it here.
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
});

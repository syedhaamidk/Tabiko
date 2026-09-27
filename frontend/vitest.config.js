import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom rather than the default node environment: the components under test
    // render real DOM and the hooks depend on browser APIs.
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.test.{js,jsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text-summary"],
      include: ["src/**/*.{js,jsx}"],
      // The generated artwork and design-token plumbing are not logic worth
      // asserting on, so they are excluded rather than left to depress the number.
      exclude: [
        "src/main.jsx",
        "src/test/**",
        "src/components/BrandMark.jsx",
        "src/components/FestivalDecor.jsx",
        "src/lib/foodIcons.js",
        "src/lib/cityData.js",
        "src/lib/mapData.js",
      ],
    },
  },
});

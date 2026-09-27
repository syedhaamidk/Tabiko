import { createContext, useCallback, useContext, useState } from "react";
import { getRestaurantTheme } from "./api";

const ThemeContext = createContext(null);

// Falls back to the default palette in global.css if a theme fetch fails —
// the app should never look broken just because theming didn't load.
//
// texture and motion are applied as data-attributes on <body> rather than
// CSS variables, since they select which CSS rule/keyframe block runs
// (see global.css: body[data-texture="..."], body[data-motion="..."])
// rather than being a single interpolatable value like a color.
function applyTokensToRoot(tokens) {
  const root = document.documentElement.style;
  if (!tokens) return;

  const { palette, font_pair, texture, motion } = tokens;
  if (palette) {
    if (palette.primary) root.setProperty("--color-primary", palette.primary);
    if (palette.secondary) root.setProperty("--color-secondary", palette.secondary);
    if (palette.background) root.setProperty("--color-background", palette.background);
    if (palette.text) root.setProperty("--color-text", palette.text);
  }
  if (font_pair) {
    if (font_pair.display) root.setProperty("--font-display", font_pair.display);
    if (font_pair.body) root.setProperty("--font-body", font_pair.body);
  }

  document.body.dataset.texture = texture || "none";
  document.body.dataset.motion = motion || "none";
}

export function ThemeProvider({ children }) {
  const [activeThemeId, setActiveThemeId] = useState(null);

  const applyThemeForRestaurant = useCallback(async (restaurantId) => {
    try {
      const { theme_id, tokens } = await getRestaurantTheme(restaurantId);
      applyTokensToRoot(tokens);
      setActiveThemeId(theme_id);
    } catch (err) {
      console.warn("Theme fetch failed, keeping default look:", err);
    }
  }, []);

  const resetTheme = useCallback(() => {
    applyTokensToRoot({
      palette: {
        primary: "#FF2E88",
        secondary: "#FFD23F",
        background: "#FFF4D6",
        text: "#2A0E1E",
      },
      font_pair: { display: "'Bungee', cursive", body: "'Fredoka', sans-serif" },
      texture: "none",
      motion: "none",
    });
    setActiveThemeId(null);
  }, []);

  return (
    <ThemeContext.Provider value={{ activeThemeId, applyThemeForRestaurant, resetTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}

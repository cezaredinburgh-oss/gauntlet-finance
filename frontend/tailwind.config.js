/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Desk-aligned slate + emerald glass palette
        surface: {
          DEFAULT: "#0b1220",
          raised: "#0f172a",
          overlay: "#1e293b",
        },
        ink: {
          DEFAULT: "#e2e8f0",
          muted: "#94a3b8",
          faint: "#64748b",
        },
        brand: {
          DEFAULT: "#38bdf8",
          soft: "#0c4a6e",
          mint: "#34d399",
        },
        danger: "#f87171",
        warn: "#fbbf24",
        ok: "#34d399",
      },
      fontFamily: {
        sans: [
          "Inter",
          "Segoe UI",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 8px 32px rgba(0,0,0,0.35)",
      },
    },
  },
  plugins: [],
};

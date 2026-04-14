/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./apps/ui/templates/**/*.html"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        surface: {
          900: "#0b0f14",
          850: "#0f1419",
          800: "#141b24",
          700: "#1a2332",
          600: "#243044",
        },
        accent: { DEFAULT: "#3b82f6", muted: "#2563eb" },
      },
    },
  },
  plugins: [],
};

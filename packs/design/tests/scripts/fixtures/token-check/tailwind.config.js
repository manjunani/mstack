// Hand-written config: literal colours, one value through a CSS variable, one computed entry.
const shared = require("./shared-colours");

module.exports = {
  content: ["./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        paper: { DEFAULT: "#ffffff", foreground: "#9ca3af" },
        brand: { 500: "#2563eb", 600: "#1d4ed8", foreground: "#ffffff" },
        surface: "hsl(var(--accent))",
        ...shared,
      },
    },
  },
};

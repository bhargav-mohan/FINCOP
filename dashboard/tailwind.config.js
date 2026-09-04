/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#000000",
        muted: "#5E5E5E",
        line: "#E2E2E2",
        wash: "#F3F3F3",
        ok: "#0D7A3F",
      },
      borderRadius: {
        uber: "8px",
      },
    },
  },
  plugins: [],
};

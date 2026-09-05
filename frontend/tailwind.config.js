/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "Liberation Mono",
          "Courier New",
          "monospace",
        ],
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgba(15, 23, 42, 0.04), 0 1px 3px 0 rgba(15, 23, 42, 0.06)",
        drawer: "-10px 0 30px -10px rgba(15, 23, 42, 0.25)",
      },
      keyframes: {
        slidein: {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
        fadein: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
      },
      animation: {
        slidein: "slidein 200ms ease-out",
        fadein: "fadein 150ms ease-out",
      },
    },
  },
  plugins: [],
};

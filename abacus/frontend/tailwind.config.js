/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  // Preflight (Tailwind's CSS reset) is off so it does not alter the existing dashboard styles.
  corePlugins: { preflight: false },
  theme: { extend: {} },
  plugins: [],
}

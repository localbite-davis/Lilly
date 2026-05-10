/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#6366f1',
        'primary-soft': '#eef2ff',
        secondary: '#0ea5e9',
        danger: '#ef4444',
        'danger-soft': '#fef2f2',
        warning: '#f59e0b',
        'warning-soft': '#fffbeb',
        success: '#10b981',
        'success-soft': '#ecfdf5',
        border: '#e2e8f0',
        'text-muted': '#64748b',
        bg: '#f8fafc',
      },
      fontFamily: {
        sans: ['Outfit', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}

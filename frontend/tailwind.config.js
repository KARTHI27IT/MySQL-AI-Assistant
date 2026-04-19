/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Add custom colors, fonts, etc. here
      colors: {
        primary: '#3B82F6',
        secondary: '#10B981',
      },
      animation: {
        'bounce-slow': 'bounce 1.5s infinite',
      }
    },
  },
  plugins: [],
}
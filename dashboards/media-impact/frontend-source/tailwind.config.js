/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        red: {
          DEFAULT: 'var(--red)',
          light: 'var(--red-light)',
        },
        navy: {
          DEFAULT: 'var(--navy)',
          light: 'var(--navy-light)',
        },
        teal: {
          DEFAULT: 'var(--teal)',
          light: 'var(--teal-light)',
        },
        mid: 'var(--mid)',
        dashboard: {
          bg: 'var(--bg)',
          border: 'var(--border)',
        }
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'sans-serif'],
      }
    },
  },
  plugins: [],
}

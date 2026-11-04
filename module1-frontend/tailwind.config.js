const colors = require('tailwindcss/colors')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Cool slate for neutrals, deep teal as the brand colour, a warm coral accent.
        gray: colors.slate,
        brand: {
          50: '#effaf8',
          100: '#d6f2ee',
          200: '#aee5de',
          300: '#7dd1c9',
          400: '#46b5ac',
          500: '#25968f',
          600: '#1b7a76',
          700: '#196260',
          800: '#184f4e',
          900: '#173f40',
        },
        accent: {
          400: '#f6a07b',
          500: '#f08a5d',
          600: '#e0703f',
        },
      },
      borderRadius: {
        DEFAULT: '0.75rem',
        lg: '1rem',
      },
      boxShadow: {
        DEFAULT: '0 1px 2px rgb(23 63 64 / 0.06), 0 8px 24px -10px rgb(23 63 64 / 0.16)',
        card: '0 1px 2px rgb(23 63 64 / 0.05), 0 12px 32px -12px rgb(23 63 64 / 0.18)',
      },
      fontFamily: {
        sans: [
          'ui-rounded',
          '"SF Pro Rounded"',
          '"Segoe UI"',
          'system-ui',
          '-apple-system',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
}

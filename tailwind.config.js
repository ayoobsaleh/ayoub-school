// هوية ثانوية أبي أيوب الأنصاري — يُبنى منها static/app.css عبر tools/build_css.sh
// indigo ← الأخضر الأساسي، slate ← الحجر والحبر، الخط IBM Plex Sans Arabic
module.exports = {
  content: ['./static/index.html'],
  theme: {
    extend: {
      fontFamily: { sans: ['"IBM Plex Sans Arabic"', 'system-ui', 'sans-serif'] },
      colors: {
        blue: {
          50: '#E3F1EE', 100: '#C7E4DD', 200: '#9CCFC3', 300: '#6AB4A5', 400: '#3C9886',
          500: '#1A806F', 600: '#0B6E5F', 700: '#095A4E', 800: '#08483F', 900: '#073A33', 950: '#04241F'
        },
        indigo: {
          50: '#E3F1EE', 100: '#C7E4DD', 200: '#9CCFC3', 300: '#6AB4A5', 400: '#3C9886',
          500: '#1A806F', 600: '#0B6E5F', 700: '#095A4E', 800: '#08483F', 900: '#073A33', 950: '#04241F'
        },
        slate: {
          50: '#F7F6F2', 100: '#F0EEE8', 200: '#E3DED3', 300: '#CFC8BA', 400: '#8A938F',
          500: '#56635F', 600: '#46514E', 700: '#333D3A', 800: '#1F2927', 900: '#172322', 950: '#0F2E2B'
        },
        brand: {
          50: '#E3F1EE', 100: '#C7E4DD', 500: '#1A806F', 600: '#0B6E5F', 700: '#095A4E', 800: '#08483F', 900: '#073A33'
        },
        gold: { 400: '#D9B45E', 500: '#C99A3B', 700: '#7A5A14' }
      }
    }
  }
}

module.exports = {
  content: [
    '../templates/**/*.html',
    '../../templates/**/*.html',
    '../../**/templates/**/*.html',
  ],
  safelist: [
    // background gradients
    'bg-gradient-to-br',
    'from-green-400',
    'via-emerald-500',
    'to-teal-600',
    // button gradients
    'from-green-500',
    'to-emerald-500',
    // text hover colors
    'hover:text-emerald-300',
  ],
  theme: {
    extend: {},
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
    require('@tailwindcss/aspect-ratio'),
  ],
}

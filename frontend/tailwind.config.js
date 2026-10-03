module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: { klop: { bg: '#07070b', card: '#111116', border: '#27272f', accent: '#f5b942', success: '#34d399', danger: '#f87171' } },
      fontFamily: { mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'] },
    },
  },
  plugins: [],
};

import './globals.css';
export const metadata = { title: 'K money — XAUUSD Terminal', description: 'K money • Exness • MetaApi • XAUUSD auto scalper' };
export const viewport = { themeColor: '#07070b', width: 'device-width', initialScale: 1 };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body className="antialiased">{children}</body></html>;
}

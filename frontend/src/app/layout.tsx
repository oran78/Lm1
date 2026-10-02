import './globals.css';
export const metadata = { title: 'Klop Apex — Trading Terminal', description: 'Exness MT5 Terminal — Klop Apex' };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body className="antialiased bg-[#09090b] text-zinc-100">{children}</body></html>;
}

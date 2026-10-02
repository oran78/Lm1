export default function StatsCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
      <p className="text-xs tracking-widest uppercase text-zinc-500">{label}</p>
      <p className={`text-2xl font-semibold mt-2 font-mono ${accent || 'text-white'}`}>{value}</p>
      {sub && <p className="text-xs text-zinc-500 mt-1">{sub}</p>}
    </div>
  );
}

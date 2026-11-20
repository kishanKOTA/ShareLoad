import Link from "next/link";

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="space-y-2">
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-900">
        ← Overview
      </Link>
      <h1 className="text-2xl font-semibold">Opportunity</h1>
      <p className="text-sm text-slate-600">
        <code>{decodeURIComponent(id)}</code> — detail view (checklist, map, impact) coming next.
      </p>
    </div>
  );
}

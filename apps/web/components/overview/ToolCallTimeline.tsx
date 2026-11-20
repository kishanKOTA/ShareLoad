import type { ToolCall } from "@/lib/types";

function formatArgs(args: ToolCall["args"]): string {
  if (!args) return "";
  return Object.values(args)
    .map((v) => (typeof v === "string" ? v : JSON.stringify(v)))
    .join(" · ");
}

export default function ToolCallTimeline({ calls }: { calls: ToolCall[] }) {
  return (
    <details className="group rounded-lg border border-slate-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-slate-800 [&::-webkit-details-marker]:hidden">
        <span className="inline-block transition-transform group-open:rotate-90">▸</span>
        Agent tool calls
        <span className="text-slate-500">({calls.length})</span>
      </summary>
      {calls.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-slate-500">No tool calls recorded for this run.</p>
      ) : (
        <ol className="relative mx-4 mb-4 border-l border-slate-200">
          {calls.map((call, i) => {
            const ok = call.ok !== false;
            return (
              <li key={i} className="ml-4 py-2">
                <span
                  className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${
                    ok ? "bg-emerald-500" : "bg-red-500"
                  }`}
                  aria-hidden
                />
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="text-xs tabular-nums text-slate-400">{i + 1}</span>
                  <code className="font-mono text-[13px] text-slate-900">{call.name}</code>
                  {call.args && Object.keys(call.args).length > 0 && (
                    <span className="font-mono text-xs text-slate-500">{formatArgs(call.args)}</span>
                  )}
                  {!ok && <span className="text-xs font-medium text-red-700">failed</span>}
                </div>
                {call.summary && <p className="mt-0.5 text-sm text-slate-600">{call.summary}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </details>
  );
}

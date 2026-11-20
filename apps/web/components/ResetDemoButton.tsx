"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useOrg } from "@/lib/org-context";

export default function ResetDemoButton() {
  const { notifyDataChanged } = useOrg();
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");

  async function reset() {
    if (
      !window.confirm(
        "Reset the demo?\n\nThis deletes all proposals, decisions and audit events, and clears the last scan, for both organizations.",
      )
    ) {
      return;
    }
    setState("busy");
    try {
      await api.resetDemo();
      notifyDataChanged();
      setState("done");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 4000);
    }
  }

  const label = {
    idle: "Reset demo",
    busy: "Resetting…",
    done: "Demo reset ✓",
    error: "Reset failed",
  }[state];

  return (
    <button
      onClick={reset}
      disabled={state === "busy"}
      className={`rounded-md border px-3 py-1 text-sm font-medium disabled:cursor-wait disabled:opacity-60 ${
        state === "error"
          ? "border-red-300 text-red-700"
          : "border-slate-300 text-slate-700 hover:bg-slate-100"
      }`}
    >
      {label}
    </button>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// Home: open an event by its ID (the public event list arrives with the waiting room, Days 5-6).
export default function Home() {
  const router = useRouter();
  const [id, setId] = useState("");
  const valid = /^[0-9a-f-]{36}$/i.test(id.trim());
  return (
    <section className="max-w-xl space-y-4">
      <h1 className="text-2xl font-semibold">Find your event</h1>
      <p className="text-slate-600 dark:text-slate-400">Paste the event ID from the organiser&apos;s link.</p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) router.push(`/event/?id=${id.trim()}`);
        }}
      >
        <input
          aria-label="Event ID"
          className="flex-1 rounded border border-slate-300 bg-white px-3 py-2 font-mono text-sm dark:border-slate-700 dark:bg-slate-900"
          placeholder="00000000-0000-0000-0000-000000000000"
          value={id}
          onChange={(e) => setId(e.target.value)}
        />
        <button
          className="rounded bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-40"
          disabled={!valid}
        >
          Open
        </button>
      </form>
    </section>
  );
}

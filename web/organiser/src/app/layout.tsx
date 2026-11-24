import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "SurgeGate organiser" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="mx-auto max-w-4xl px-4 py-6">
        <header className="mb-6 flex items-center justify-between">
          <a href="/organiser/events" className="text-lg font-semibold">
            SurgeGate · organiser
          </a>
          <form action="/organiser/api/logout" method="post">
            <button className="text-sm text-slate-500 underline">Sign out</button>
          </form>
        </header>
        {children}
      </body>
    </html>
  );
}

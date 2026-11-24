export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <form action="/organiser/api/login" method="post" className="max-w-sm space-y-3">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      {error && <p className="rounded bg-red-100 px-3 py-2 text-red-800">{error}</p>}
      <input name="email" type="email" required placeholder="Email" className="w-full rounded border px-3 py-2 text-slate-900" />
      <input name="password" type="password" required placeholder="Password" className="w-full rounded border px-3 py-2 text-slate-900" />
      <button className="rounded bg-indigo-600 px-5 py-2 font-medium text-white">Sign in</button>
    </form>
  );
}

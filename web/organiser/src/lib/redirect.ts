// Redirects with a RELATIVE Location. Behind CloudFront -> ALB the request URL the server sees is
// its own pod address (http://0.0.0.0:8000/...), so absolute redirects built from req.url would
// send the browser there. A relative path keeps the browser on whatever host it used.
export function seeOther(path: string, query?: Record<string, string>): Response {
  const qs = query && Object.keys(query).length ? `?${new URLSearchParams(query)}` : "";
  return new Response(null, { status: 303, headers: { Location: `${path}${qs}` } });
}

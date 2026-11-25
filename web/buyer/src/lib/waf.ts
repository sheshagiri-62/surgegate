// AWS WAF challenge (Day 9 Task 2): CloudFront's web ACL challenges POST /queue/<event>/join.
// A fetch() can't solve that challenge page, so before joining we load AWS's challenge.js
// (NEXT_PUBLIC_WAF_SDK_URL) and let it get an aws-waf-token: it runs a short proof-of-work in
// the browser and stores the token as a cookie on our domain, which the join request then
// carries. Scripts without a browser (curl, bots) get the challenge instead.
// Empty URL (local dev without WAF) = no-op.

const SDK_URL = process.env.NEXT_PUBLIC_WAF_SDK_URL ?? "";

interface AwsWafIntegration {
  getToken(): Promise<string>;
  hasToken(): boolean;
}

declare global {
  interface Window {
    AwsWafIntegration?: AwsWafIntegration;
  }
}

let loading: Promise<void> | null = null;

function loadSdk(): Promise<void> {
  if (typeof window === "undefined" || !SDK_URL) return Promise.resolve();
  if (window.AwsWafIntegration) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SDK_URL;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loading = null;
      reject(new Error("could not load the WAF challenge script"));
    };
    document.head.appendChild(s);
  });
  return loading;
}

/** Make sure the browser holds a valid aws-waf-token before a challenged request. */
export async function ensureWafToken(): Promise<void> {
  if (!SDK_URL) return;
  await loadSdk();
  const waf = window.AwsWafIntegration;
  if (waf && !waf.hasToken()) await waf.getToken();
}

/** A WAF challenge also answers 202, so tell it apart from the API's own 202 by its header. */
export function isWafChallenge(r: Response): boolean {
  return (r.headers.get("x-amzn-waf-action") ?? "").toLowerCase() === "challenge";
}

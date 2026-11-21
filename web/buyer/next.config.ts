import type { NextConfig } from "next";

// Static export: the buyer site is plain files (S3 + CloudFront later), so 50,000 page loads
// at sale time never reach a server. All dynamic data comes from API calls in the browser.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default nextConfig;

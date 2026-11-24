import type { NextConfig } from "next";

// Organiser dashboard: server-side rendered on EKS (blueprint), behind CloudFront -> ALB rule
// /organiser*. `standalone` makes a small self-contained server for the container image.
const nextConfig: NextConfig = {
  output: "standalone",
  basePath: "/organiser",
  poweredByHeader: false,
};

export default nextConfig;

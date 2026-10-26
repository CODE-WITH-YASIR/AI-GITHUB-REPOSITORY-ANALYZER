import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow Vercel serverless functions to have longer timeouts where possible
  experimental: {},
  // Ensure API routes are treated as server-only
  serverExternalPackages: [],
};

export default nextConfig;

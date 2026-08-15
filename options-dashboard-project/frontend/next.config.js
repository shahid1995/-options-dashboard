/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    // Backend API base URL (user-hosted Railway deployment). Override at
    // build time with NEXT_PUBLIC_API_URL if the backend moves.
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL || "https://options-dashboard-production-fb47.up.railway.app",
  },
};
module.exports = nextConfig;

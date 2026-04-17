/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  allowedDevOrigins: ["192.168.1.101", "localhost", "127.0.0.1", "app.digidle.com"],
  // Root → /chat redirect at HTTP level (no SSR required, instant 307).
  async redirects() {
    return [{ source: "/", destination: "/chat", permanent: false }];
  },
  // Point file tracing to the frontend directory so Next.js doesn't
  // get confused by the parent-level lockfile
  outputFileTracingRoot: __dirname,
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "img.clerk.com",
      },
    ],
  },
};

module.exports = nextConfig;

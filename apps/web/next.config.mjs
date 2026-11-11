/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Workspace packages ship TypeScript sources, so Next must transpile them.
  transpilePackages: ["@email-platform/api-client", "@email-platform/shared-schemas"],
};

export default nextConfig;

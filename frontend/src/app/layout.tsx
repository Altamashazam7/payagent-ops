import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PayAgent Ops | Commerce Operations",
  description: "AI-assisted commerce operations with human-controlled actions.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

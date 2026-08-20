import type { Metadata } from "next";
import "./globals.css";
import { TopBar } from "@/components/top-bar";

export const metadata: Metadata = {
  title: "Agent Fleet",
  description: "Agent Fleet Control Plane",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <TopBar />
        <main>{children}</main>
      </body>
    </html>
  );
}

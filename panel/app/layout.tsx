import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@/styles/tokens.css";

export const metadata: Metadata = {
  title: "Agent Fleet Control Panel",
  description: "Control plane for the agent fleet.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/*
          /DESIGN.md §1.2 (Nocturne — Font Loading) prescribes this exact
          preconnect + stylesheet markup for Inter 400/500/600. The Next.js
          no-page-custom-font rule targets the pages/ router; the App Router
          renders <head> per the documented visual contract, so the rule is
          disabled for this line with that justification.
        */}
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}

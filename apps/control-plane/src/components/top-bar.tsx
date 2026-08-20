"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navLinks = [
  { href: "/agents", label: "Agents" },
  { href: "/repos", label: "Repos" },
] as const;

export function TopBar() {
  const pathname = usePathname();

  return (
    <header className="flex h-12 items-center border-b border-gray-200 bg-white px-6">
      <Link href="/agents" className="text-lg font-semibold text-gray-900">
        Agent Fleet
      </Link>
      <nav className="ml-8 flex gap-4" aria-label="Main navigation">
        {navLinks.map((link) => {
          const isActive = pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`text-sm font-medium transition-colors ${
                isActive
                  ? "text-blue-700 underline underline-offset-4"
                  : "text-gray-600 hover:text-gray-900"
              }`}
              aria-current={isActive ? "page" : undefined}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}

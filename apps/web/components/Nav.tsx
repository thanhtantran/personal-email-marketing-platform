"use client";

/**
 * Primary navigation.
 *
 * A small client component so the active link can be highlighted from the
 * current pathname; the root layout stays a server component.
 */

import type { CSSProperties } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@email-platform/api-client";

const LINKS: { href: string; label: string }[] = [
  { href: "/", label: "Dashboard" },
  { href: "/contacts", label: "Audience" },
  { href: "/segments", label: "Segments" },
  { href: "/imports", label: "Imports" },
  { href: "/campaigns", label: "Campaigns" },
  { href: "/providers", label: "Providers" },
  { href: "/templates", label: "Templates" },
];

const navStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 16,
  flexWrap: "wrap",
  padding: "12px 24px",
  borderBottom: "1px solid #2a2f3a",
  background: "#0f131a",
};

const brandStyle: CSSProperties = { fontWeight: 600, fontSize: 14, whiteSpace: "nowrap" };

const linksStyle: CSSProperties = { display: "flex", gap: 4, flexWrap: "wrap" };

const baseLinkStyle: CSSProperties = {
  padding: "5px 10px",
  borderRadius: 6,
  fontSize: 13,
  textDecoration: "none",
  color: "#9aa4b2",
};

const activeLinkStyle: CSSProperties = {
  ...baseLinkStyle,
  color: "#e6e8ee",
  background: "#1b2130",
};

const signOutStyle: CSSProperties = {
  ...baseLinkStyle,
  background: "none",
  border: "none",
  cursor: "pointer",
};

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // A missing or expired session is not worth surfacing; just leave.
    }
    router.push("/signin");
    router.refresh();
  }

  return (
    <nav style={navStyle}>
      <span style={brandStyle}>Email Marketing Platform</span>
      <div style={linksStyle}>
        {LINKS.map((link) => {
          const active =
            link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          return (
            <Link key={link.href} href={link.href} style={active ? activeLinkStyle : baseLinkStyle}>
              {link.label}
            </Link>
          );
        })}
        <button type="button" style={signOutStyle} onClick={handleSignOut}>
          Sign out
        </button>
      </div>
    </nav>
  );
}

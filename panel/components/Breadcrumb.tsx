import Link from "next/link";
import { Fragment } from "react";

import { RowChevronIcon } from "./icons";
import styles from "./Breadcrumb.module.css";

/**
 * Breadcrumb — /DESIGN.md §11.2. Navigational trail. Presentational and
 * server-safe; internal links use next/link. The active (last) item renders
 * as plain text and is marked `aria-current="page"`. Wrapped in a
 * <nav aria-label="Breadcrumb"> for assistive tech.
 */
export interface BreadcrumbItem {
  label: string;
  href?: string;
  active?: boolean;
}

export interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  return (
    <nav aria-label="Breadcrumb" className={[styles.crumbs, className].filter(Boolean).join(" ")}>
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        const active = item.active ?? isLast;
        return (
          <Fragment key={`${item.label}-${i}`}>
            {i > 0 && (
              <span className={styles.sep} aria-hidden="true">
                <RowChevronIcon size={12} weight="bold" />
              </span>
            )}
            {active || !item.href ? (
              <span className={styles.current} aria-current={active ? "page" : undefined}>
                {item.label}
              </span>
            ) : (
              <Link href={item.href} className={styles.link}>
                {item.label}
              </Link>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}

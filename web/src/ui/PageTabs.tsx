import type { ReactNode } from "react";
import { cx } from "./cx";
import styles from "./PageTabs.module.css";

export interface PageTabsProps {
  // Accessible name for the nav landmark — passed in already-translated so the
  // kit stays string-free.
  label: string;
  className?: string;
  children: ReactNode;
}

// Chiclet-style link-tab strip for URL-driven sub-page navigation (the
// sndwrks-local tab look: outlined chips, lowercase mono, accent border when
// active). Router-agnostic: the app fills `children` with its own links (e.g.
// React Router NavLink) wrapping <PageTab>, the same contract as
// Sidebar/SidebarItem. For state-driven tab panels use Tabs instead.
export function PageTabs({ label, className, children }: PageTabsProps) {
  return (
    <nav aria-label={label} className={cx(styles.list, className)}>
      {children}
    </nav>
  );
}

export interface PageTabProps {
  label: string;
  active?: boolean;
}

// Presentational tab chip. Compose with the app's router link, e.g.:
//   <NavLink to="invoices">{({ isActive }) =>
//     <PageTab label={t('invoices')} active={isActive} />}</NavLink>
export function PageTab({ label, active = false }: PageTabProps) {
  return <span className={cx(styles.tab, active && styles.tabActive)}>{label}</span>;
}

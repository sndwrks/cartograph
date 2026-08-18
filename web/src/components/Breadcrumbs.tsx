import { Link } from "react-router-dom";

import styles from "./Breadcrumbs.module.css";

export interface Crumb {
  label: string;
  to?: string;
}

export default function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className={styles.breadcrumbs}>
      {crumbs.map((crumb, index) => (
        <span key={`${crumb.label}-${index}`}>
          {index > 0 && <span className={styles.crumbSep}>›</span>}
          {crumb.to ? (
            <Link to={crumb.to}>{crumb.label}</Link>
          ) : (
            <span className={styles.crumbCurrent}>{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

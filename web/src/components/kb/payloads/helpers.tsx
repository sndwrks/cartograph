import type { ReactNode } from "react";

import { Badge } from "../../../ui";
import styles from "./payload.module.css";

export type Payload = Record<string, unknown>;

export interface PayloadProps {
  payload: Payload;
}

export function str(payload: Payload, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value.trim() : "";
}

export function list(payload: Payload, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && !!item.trim());
}

export function records(payload: Payload, key: string): Payload[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Payload => typeof item === "object" && item !== null,
  );
}

/** A titled block that renders nothing at all when it has no content. */
export function Section({
  heading,
  children,
}: {
  heading: string;
  children: ReactNode;
}) {
  if (!children) return null;
  return (
    <section className={styles.section}>
      <h4 className={styles.heading}>{heading}</h4>
      {children}
    </section>
  );
}

export function Prose({ heading, text }: { heading: string; text: string }) {
  if (!text) return null;
  return (
    <Section heading={heading}>
      <p className={styles.prose}>{text}</p>
    </Section>
  );
}

export function Items({
  heading,
  items,
  ordered = false,
}: {
  heading: string;
  items: string[];
  ordered?: boolean;
}) {
  if (items.length === 0) return null;
  const List = ordered ? "ol" : "ul";
  return (
    <Section heading={heading}>
      <List className={styles.list}>
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </List>
    </Section>
  );
}

export function Chips({ heading, items }: { heading: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Section heading={heading}>
      <div className={styles.chips}>
        {items.map((item) => (
          <Badge key={item}>{item}</Badge>
        ))}
      </div>
    </Section>
  );
}

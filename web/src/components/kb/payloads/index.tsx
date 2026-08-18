import type { ComponentType } from "react";

import ConventionPayload from "./ConventionPayload";
import DecisionPayload from "./DecisionPayload";
import FallbackPayload from "./FallbackPayload";
import GlossaryPayload from "./GlossaryPayload";
import RunbookPayload from "./RunbookPayload";
import SpecificationPayload from "./SpecificationPayload";
import type { PayloadProps } from "./helpers";

/**
 * Mirrors the backend's KbType registry. Keyed on the type STRING with a
 * fallback, so a sixth backend type ships without a frontend release: it
 * renders through FallbackPayload until someone writes a nicer one.
 */
const RENDERERS: Record<string, ComponentType<PayloadProps>> = {
  glossary: GlossaryPayload,
  specification: SpecificationPayload,
  decision: DecisionPayload,
  convention: ConventionPayload,
  runbook: RunbookPayload,
};

export function payloadRenderer(type: string): ComponentType<PayloadProps> {
  return RENDERERS[type] ?? FallbackPayload;
}

export { FallbackPayload };

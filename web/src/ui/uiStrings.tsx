import { createContext, useContext, type ReactNode } from "react";

/**
 * The handful of user-facing strings cloud-ui renders on its own (icon-button
 * labels, region names). The package stays i18n-agnostic: apps wrap their tree
 * once in <UiStringsProvider strings={{ close: t('close'), … }}> with
 * translated values; without a provider the English defaults apply.
 */
export interface UiStrings {
  /** aria-label for the ×-close buttons in Dialog / Drawer / Toast. */
  readonly close: string;
  /** aria-label for the toast notifications region (hotkey suffix is Radix's). */
  readonly notifications: string;
}

export const DEFAULT_UI_STRINGS: UiStrings = {
  close: "Close",
  notifications: "Notifications",
};

const UiStringsContext = createContext<UiStrings>(DEFAULT_UI_STRINGS);

export function UiStringsProvider({
  strings,
  children,
}: {
  strings: Partial<UiStrings>;
  children: ReactNode;
}) {
  return (
    <UiStringsContext.Provider value={{ ...DEFAULT_UI_STRINGS, ...strings }}>
      {children}
    </UiStringsContext.Provider>
  );
}

export const useUiStrings = (): UiStrings => useContext(UiStringsContext);

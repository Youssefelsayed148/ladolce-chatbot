/**
 * La Dolce Saveur brand tokens — the single source of truth for the chat widget.
 *
 * Every value here was extracted from the LIVE site (ladolcesaveur.com), not
 * guessed: colours from the compiled Tailwind classes in
 * /assets/index-BB4kNphy.css (e.g. `.bg-brand-darkGreen{...rgb(29 47 21)...}`)
 * and the metallic-gold accents used inline in the app bundle (#d4af37 family);
 * fonts from the site's `font-family` declarations and the Google Fonts it loads.
 *
 * Components import from here — no colour or font is hardcoded inline elsewhere.
 */

export const colors = {
  // Primary brand green (the site's dominant colour — body bg + primary actions).
  darkGreen: "#1d2f15", // rgb(29 47 21) — .bg-brand-darkGreen
  darkGreenDeep: "#122215", // deepest shade used for gradients/overlays
  green: "#375a28", // mid green for hovers/accents
  greenBright: "#386c41", // brighter green highlight

  // Cream / ivory neutrals (light surfaces + text on dark).
  cream: "#faf6f0", // rgb(250 246 240) — .bg-brand-cream
  creamSoft: "#faf7f2", // .text-brand-gold token (used as light text on green)
  creamDeep: "#f5f2eb", // slightly deeper cream for insets
  ivory: "#fdfcfa",

  // Metallic gold accents (used inline across the site: #d4af37 & friends).
  gold: "#d4af37",
  goldLight: "#fceba1",
  goldSoft: "#d8c392",
  goldMuted: "#c5a880",

  // Supporting UI neutrals (consistent with the existing OrderSummary/Confirm
  // components already in /web).
  border: "#d9cbb8",
  divider: "#ece3d5",
  textMuted: "#6d7081",

  // Status.
  danger: "#a3352f",
  successBg: "#eef6ec",
  successText: "#3f5136",
} as const;

export const gradients = {
  gold: `linear-gradient(135deg, ${colors.gold} 0%, ${colors.goldLight} 50%, ${colors.goldSoft} 100%)`,
  green: `linear-gradient(160deg, ${colors.darkGreen} 0%, ${colors.darkGreenDeep} 100%)`,
} as const;

export const fonts = {
  /** Hero / logotype — the site's display face. */
  display: `"Aboreto", "Cormorant Garamond", serif`,
  /** Elegant serif for headings and product names. */
  heading: `"Cormorant Garamond", Georgia, serif`,
  /** Small-caps luxe eyebrow labels. */
  eyebrow: `"Cinzel", "Cormorant Garamond", serif`,
  /** Body / UI copy. */
  body: `"Space Grotesk", "Montserrat", system-ui, -apple-system, sans-serif`,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

export const shadows = {
  // Soft, warm-tinted elevation (green-black rather than neutral black).
  card: "0 8px 24px rgba(29, 47, 21, 0.10)",
  panel: "0 24px 60px rgba(18, 34, 21, 0.28)",
  launcher: "0 10px 30px rgba(29, 47, 21, 0.35)",
  focusRing: `0 0 0 3px ${colors.gold}66`,
} as const;

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const layout = {
  panelWidth: 400,
  panelHeight: 620,
  launcherSize: 62,
  zWidget: 2147483000, // sit above typical site chrome when embedded
} as const;

export const motion = {
  fast: "140ms cubic-bezier(0.4, 0, 0.2, 1)",
  base: "240ms cubic-bezier(0.22, 1, 0.36, 1)",
  panel: "360ms cubic-bezier(0.22, 1, 0.36, 1)",
} as const;

export const theme = {
  colors,
  gradients,
  fonts,
  radius,
  shadows,
  space,
  layout,
  motion,
} as const;

export type Theme = typeof theme;

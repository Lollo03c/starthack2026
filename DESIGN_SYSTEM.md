# ChainIQ Design System

Merged aesthetic: **SceneSnap** shapes/typography/vibe + **ChainIQ** color palette.

---

## Color Tokens

All colors are defined as CSS custom properties on `:root` in `static/index.html`.

### Primary
| Token | Value | Usage |
|-------|-------|-------|
| `--ciq-red` | `#ec1e24` | Primary brand accent, CTAs, active states |
| `--ciq-red-hover` | `#d41920` | Hover state for primary buttons |
| `--ciq-red-light` | `#fef2f2` | Light red backgrounds (preferred badges, top row highlight) |
| `--ciq-red-muted` | `#f87171` | Softer red for animations, loading indicators |

### Neutrals
| Token | Value | Usage |
|-------|-------|-------|
| `--ciq-black` | `#0a0a0a` | Primary text, hero headlines |
| `--ciq-charcoal` | `#1a1a1a` | Top bars, dark surfaces |
| `--ciq-dark-gray` | `#32373c` | Secondary buttons, strong labels |
| `--ciq-mid-gray` | `#949494` | Muted text, section labels, placeholders |
| `--ciq-light-gray` | `#e5e7eb` | Borders, dividers |
| `--ciq-off-white` | `#f7f7f8` | Page background, sunken surfaces |
| `--ciq-white` | `#ffffff` | Card backgrounds, text on dark |

### Accent
| Token | Value | Usage |
|-------|-------|-------|
| `--ciq-blue` | `#0693e3` | Links (inherited from ChainIQ) |
| `--ciq-blue-light` | `#e0f2fe` | Light link backgrounds |

### Semantic
| Token | Value | Usage |
|-------|-------|-------|
| `--ciq-success` | `#16a34a` | Can Proceed, forward button, compliant badge |
| `--ciq-success-light` | `#f0fdf4` | Success banner backgrounds |
| `--ciq-success-border` | `#bbf7d0` | Success banner borders |
| `--ciq-warning` | `#d97706` | Conditions Apply, INFO escalations, inferred fields |
| `--ciq-warning-light` | `#fffbeb` | Warning backgrounds |
| `--ciq-warning-border` | `#fde68a` | Warning borders |
| `--ciq-danger` | `#dc2626` | Blocked, BLOCKING escalations, non-compliant |
| `--ciq-danger-light` | `#fef2f2` | Danger backgrounds |
| `--ciq-danger-border` | `#fecaca` | Danger borders |

### Surface System
| Token | Value | Usage |
|-------|-------|-------|
| `--ciq-surface` | white | Cards, raised panels |
| `--ciq-surface-raised` | white | Elevated cards |
| `--ciq-surface-sunken` | off-white | Page background, metric boxes |
| `--ciq-border` | light-gray | Default borders |
| `--ciq-border-subtle` | `#f0f0f0` | Table row dividers |

---

## Typography

| Element | Font | Weight | Size | Notes |
|---------|------|--------|------|-------|
| Hero heading | Satoshi | 900 (black) | 2.25rem (text-4xl) | Letter-spacing: -0.02em |
| Section heading | Satoshi | 700 (bold) | 1rem (text-base) | -- |
| Section label | Satoshi | 700 (bold) | 0.6875rem (text-xs) | Uppercase, widest tracking |
| Body text | Satoshi | 400 | 0.875rem (text-sm) | Line-height: 1.65 |
| Table text | Satoshi | 400/700 | 0.75rem (text-xs) | Mono for prices |
| Badge text | Satoshi | 900 (black) | 0.6875rem (text-[11px]) | Uppercase in BLOCKING/INFO |
| Metric label | Satoshi | 700 | 0.6875rem (text-[11px]) | Uppercase, wide tracking |
| Metric value | Satoshi | 700 | 0.875rem (text-sm) | -- |

Font loaded via: `https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700,900&display=swap`

---

## Spacing Scale

Uses Tailwind defaults with these patterns:
- Section gaps: `space-y-6` (1.5rem)
- Card padding: `p-4` to `p-5` (1rem to 1.25rem)
- Metric grid gaps: `gap-3` (0.75rem)
- Chat bubble padding: `0.75rem 1rem`
- Top bar padding: `px-6 py-3`

---

## Border Radius Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 8px | Small buttons, inputs, logo mark |
| `--radius-md` | 12px | Buttons, metric boxes, input fields |
| `--radius-lg` | 16px | Chat bubbles, status banners, tables |
| `--radius-xl` | 20px | Cards, escalation panels, analysis sections |
| `--radius-2xl` | 24px | Hero chat bar |
| `--radius-full` | 9999px | Badges, pills, status dots |

---

## Shadow Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.04)` | Cards at rest |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.06)` | Hovered cards, buttons |
| `--shadow-lg` | `0 8px 30px rgba(0,0,0,0.08)` | Hero chat bar, modals |
| `--shadow-input-focus` | `0 0 0 3px rgba(236,30,36,0.12)` | Input focus ring (ChainIQ red glow) |

---

## Component Variants

### Buttons
- **Primary** (`.ciq-btn-primary`): ChainIQ red bg, white text, lifts 1px on hover
- **Secondary** (`.ciq-btn-secondary`): Dark gray bg, white text
- **Ghost**: Transparent bg, border, text inherits — used for "New Request", "Show ranking"

### Chat Bubbles
- **User** (`.msg-user`): Charcoal background, white text, rounded top-left/top-right/bottom-left
- **AI** (`.msg-ai`): White background, subtle border, rounded top-right/bottom-right/bottom-left

### Top Bar
`.ciq-topbar`: Charcoal background, blurred, with red CQ logo mark. All text is white/semi-transparent white.

### Cards
`.ciq-card`: White bg, subtle border, `--radius-xl` corners, lifts shadow on hover.

### Tables
`.ciq-table`: White bg within a rounded border container. Header row uses sunken background. Rows highlight on hover with `--ciq-surface-sunken`. Top-ranked row uses `--ciq-red-light`.

### Escalation Cards
- **Blocking**: Red light background, red border, bold red BLOCKING badge
- **Info**: Warning light background, warning border, amber INFO badge

### Status Banners
- **Can Proceed**: Green success light bg, checkmark circle, bold green text
- **Conditions Apply**: Compact amber strip with dot indicator
- **Blocked**: Compact red strip with dot indicator

### Suggestion Chips
Pill-shaped, bordered, default text-secondary. On hover: border and text turn ChainIQ red.

---

## Motion

| Pattern | Duration | Easing | Usage |
|---------|----------|--------|-------|
| Button hover | 150ms | ease | Background color, Y-translate lift |
| Card hover | 250ms | `--ease-out` | Shadow elevation |
| Table row hover | 150ms | ease | Background color |
| Input focus | instant | -- | Border color + box-shadow ring |
| Panel reveal | 350ms | `--ease-out` | Staggered `panelFadeIn` (80ms per section) |
| Chat bubble appear | 500ms | `--ease-out` | `fadeSlideUp` |
| Phase transition | 400ms | `--ease-out` | `fadeSlideDown` / `fadeIn` |

`--ease-out` = `cubic-bezier(0.16, 1, 0.3, 1)` — smooth deceleration, feels premium.

---
name: Aegis HUD
colors:
  surface: '#111417'
  surface-dim: '#111417'
  surface-bright: '#37393d'
  surface-container-lowest: '#0c0e12'
  surface-container-low: '#191c1f'
  surface-container: '#1d2023'
  surface-container-high: '#282a2e'
  surface-container-highest: '#323539'
  on-surface: '#e1e2e7'
  on-surface-variant: '#bac9cc'
  inverse-surface: '#e1e2e7'
  inverse-on-surface: '#2e3134'
  outline: '#849396'
  outline-variant: '#3b494c'
  surface-tint: '#00daf3'
  primary: '#c3f5ff'
  on-primary: '#00363d'
  primary-container: '#00e5ff'
  on-primary-container: '#00626e'
  inverse-primary: '#006875'
  secondary: '#95d0d8'
  on-secondary: '#00363c'
  secondary-container: '#034f56'
  on-secondary-container: '#83bfc7'
  tertiary: '#ffe7e2'
  on-tertiary: '#621100'
  tertiary-container: '#ffc2b3'
  on-tertiary-container: '#aa2600'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#9cf0ff'
  primary-fixed-dim: '#00daf3'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004f58'
  secondary-fixed: '#b0edf5'
  secondary-fixed-dim: '#95d0d8'
  on-secondary-fixed: '#001f23'
  on-secondary-fixed-variant: '#034f56'
  tertiary-fixed: '#ffdad2'
  tertiary-fixed-dim: '#ffb4a2'
  on-tertiary-fixed: '#3c0700'
  on-tertiary-fixed-variant: '#8a1d00'
  background: '#111417'
  on-background: '#e1e2e7'
  surface-variant: '#323539'
typography:
  display-lg:
    fontFamily: Space Grotesk
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Space Grotesk
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: 0.05em
  headline-sm:
    fontFamily: Space Grotesk
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 28px
    letterSpacing: 0.1em
  body-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.2em
  data-numeric:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: '500'
    lineHeight: 24px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Space Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
spacing:
  unit: 4px
  gutter: 16px
  margin-edge: 32px
  widget-gap: 24px
  container-padding: 12px
---

## Brand & Style
The design system is an immersive, high-fidelity digital interface inspired by advanced tactical telemetry and cinematic heads-up displays (HUD). It evokes a sense of hyper-intelligence, precision, and military-grade sophistication. 

The aesthetic is **Holographic / Glassmorphism**, characterized by:
- **Optical Depth:** Layers are defined by varying levels of translucency and additive color blending rather than opaque surfaces.
- **Kinetic Energy:** The UI feels "powered on," with glowing borders and vibrant light-emitting elements.
- **Technical Rigor:** Every element looks functional, featuring micro-grids, coordinate markers, and data-dense widgets that suggest a live, streaming environment.
- **Stark Minimalism:** Despite the density, the layout remains organized through a strict adherence to geometric primitives (circles and right angles) and a singular monochromatic accent palette.

## Colors
The palette is built on a "Void and Neon" philosophy. 
- **The Void (#05070A):** A near-black base provides maximum contrast for emissive elements and ensures the UI is comfortable for long-term monitoring in low-light environments.
- **The Core (#00E5FF):** A vibrant Cyan used for primary data, active states, and glowing accents. It is intended to look like light, not paint.
- **Sub-Current (#004D54):** A muted, deep teal used for secondary containers, inactive states, and background grid lines.
- **Warning (#FF3D00):** A high-contrast orange reserved strictly for critical errors, system breaches, or high-priority alerts.

All surfaces should use `glass_surface` with a backdrop-blur of at least 8px to simulate holographic projection.

## Typography
The typography system balances the technical precision of monospaced fonts with the modern readability of geometric sans-serifs.
- **Space Grotesk** is used for headlines and primary headers to provide a futuristic, wide-aperture feel.
- **JetBrains Mono** is the workhorse for all data, labels, and body text, emphasizing the "coded" and "computed" nature of the interface.
- **Styling Note:** Always use `label-caps` for metadata tags and secondary navigation. Headlines should occasionally feature a "glitch" or "scanline" text-shadow effect in high-priority views.

## Layout & Spacing
The layout follows a **Fluid HUD** model. Instead of a traditional web grid, it utilizes a "Corner-Anchored" philosophy where critical telemetry lives in the screen peripheries, leaving the center open for primary visualization.

- **The HUD Margin:** A mandatory 32px safe area on all sides mimics a helmet or monitor overlay.
- **Micro-Grids:** Backgrounds should feature a subtle 20px x 20px grid of dots or thin lines in `secondary_color` at 10% opacity.
- **Widget Modularization:** Components are grouped into "modules" that snap to a 4px baseline. Vertical spacing is tight to maximize data density, while horizontal spacing remains generous to ensure legibility.

## Elevation & Depth
In this design system, depth is communicated through **Luminance and Opacity** rather than shadows.
- **Level 0 (Background):** Solid `#05070A`.
- **Level 1 (Sub-surface):** Semi-transparent layers (4% opacity) with thin `0.5px` borders.
- **Level 2 (Active Widget):** Glow effects (`glow_intensity`) applied to borders and icons to pull them forward in space.
- **Level 3 (Overlay/Modal):** High-contrast cyan borders (1.5px) with a heavy backdrop-blur (16px) and a subtle animated scanline texture.

## Shapes
This design system utilizes a **Sharp & Geometric** shape language. 
- **Corners:** Standard containers use 0px radius (Sharp) to maintain a military/industrial look.
- **Angular Cuts:** Use 45-degree chamfered corners on buttons and primary headers to evoke the "Stark" aesthetic.
- **Circular Geometry:** Gauges, progress rings, and biometric scanners should be perfect circles, often composed of broken or dashed arcs to look like rotating mechanical parts.

## Components
- **Buttons:** Sharp-edged, transparent backgrounds with a `1px` primary border. On hover, the background fills with a 10% primary tint and a central glow.
- **Circular Gauges:** Central to the HUD. Use concentric rings with dashed strokes. The primary data (e.g., %) sits in the center using `display-lg` typography.
- **Input Fields:** L-shaped border accents at the corners rather than a full box. Labels should float above the input in `label-caps`.
- **Status Chips:** Small, rectangular tags with a background glow corresponding to the status (Cyan for OK, Orange for Alert).
- **Data Tables:** No vertical lines. Horizontal dividers are 0.5px thick with 20% opacity. Rows highlight with a cyan "bracket" on the far left when hovered.
- **Crosshairs & Brackets:** Use thin, decorative corner brackets around important image or video feeds to simulate targeting systems.
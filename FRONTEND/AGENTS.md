# Project Design Guidelines: news cloud

This document preserves the core design identity of the **news cloud** application.

## Visual Identity
- **Theme:** Dark, futuristic, and professional.
- **Background:** Interactive Canvas-based space background (`InteractiveSpaceBackground.tsx`).
  - Stars react to mouse movement (parallax).
  - Stars twinkle at random speeds.
  - No trailing effects for a clean look.
- **Glassmorphism:** Use `bg-zinc-900/80` with `backdrop-blur-md` for main containers.
- **Typography:** 
  - Brand name: "news cloud" (lowercase, bold).
  - Headings: Use `SlotText` for animated transitions.

## Animation Patterns
- **Slot Machine Text:** Headings must use the `SlotText` component.
  - Direction: Old text exits to the bottom (`y: 100%`), new text enters from the top (`y: -100%`).
  - Mode: Sequential (`mode="wait"`) with a snappy delay (0.1s - 0.2s).
- **Step Transitions:** Content should slide out to the left (`x: -50`) and new content should slide in from the right (`x: 50`).
- **Staggered Entrances:** Social buttons and list items should use staggered animations for a premium feel.

## Component Specifics
- **Social Logins:** 
  - Arranged in a single vertical column.
  - Official branding:
    - Google: White background, official logo.
    - Apple: Black background, white logo.
    - Microsoft: White background, official logo.
- **Success State:**
  - Green checkmark with a matching green pulse animation (`bg-green-500/20`).
  - Confetti effect on completion.
  - Automatic redirection after 3 seconds.

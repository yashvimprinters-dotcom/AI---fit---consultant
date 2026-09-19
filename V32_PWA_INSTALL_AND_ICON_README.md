# FITORA V32 — PWA install + Android icon fix

- Added cache-busted Web App Manifest (`/manifest.webmanifest?v=32`).
- Added separate `any` and `maskable` 192px/512px icons plus common Android sizes.
- Added PWA install button with download arrow in the FITORA header.
- Added explicit `beforeinstallprompt` handling and a fallback install instruction.
- Existing FITORA functionality is preserved.

Important: an already-created Android home-screen shortcut can retain its old icon. Delete the old FITORA shortcut, open the updated site in Chrome, and install again.

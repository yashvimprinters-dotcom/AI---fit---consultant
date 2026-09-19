# FITORA V33 — In-App Download / Install Option

This version adds a built-in **Get FITORA on your phone / Download / Install FITORA** option inside the customer account menu and Settings.

## Behavior
- Uses the browser's PWA install prompt when available.
- If the browser does not expose the install prompt, gives Android Chrome instructions to use **⋮ → Install app**.
- Detects standalone mode and avoids offering a second installation once FITORA is already installed.
- Keeps the existing FITORA PWA manifest, branded icons, service worker, and install button.
- Adds cache-busted manifest reference `?v=33`.

## Important
This is a PWA installation, not a native APK download. It installs FITORA from the web as an app-like experience. A Play Store/native APK build would be a separate packaging step.

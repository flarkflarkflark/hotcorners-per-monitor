# Deterministic Plasma/KWin X11 tap/linger gate

This gate uses a temporary KWin script package with ID `hotcorners-per-monitor-gate`.
It preserves the production path from `handleCorner()` through live context
resolution, QTimer-backed tap/linger decisions, stay-zone handling, cooldown,
and dispatch. It substitutes only:

- physical electric-border ingress with KWin `registerShortcut` hooks;
- physical cursor coordinates with explicit 8 px / 9 px gate coordinates;
- final gate marker shortcuts with monotonic journal markers.

The production source tree is not modified. See `instrumentation.diff`.
A separate real-edge smoke remains necessary to prove `registerScreenEdge()`
can reach `handleCorner()`; this deterministic gate intentionally does not
measure VirtualBox pointer-edge reliability.

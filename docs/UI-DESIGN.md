# Desktop appearance

Deadlock is a local monitoring utility. Home answers two questions: how is the machine doing, and which agents need attention? This web implementation takes its visual principles from Apple's HIG without imitating native window chrome.

References: [Apple design skill](https://github.com/dickwu/apple-design-skill), [layout](https://developer.apple.com/design/human-interface-guidelines/layout), [typography](https://developer.apple.com/design/human-interface-guidelines/typography), [accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [charting data](https://developer.apple.com/design/human-interface-guidelines/charting-data), and [dark appearance](https://developer.apple.com/design/human-interface-guidelines/dark-mode).

The skill's improvement workflow informed these choices:

- System type for controls and content; system monospace only for data. 32px page titles, 17px sections, 13px body, and 11–12px supporting text.
- Neutral surfaces, blue actions, green healthy states, and amber warnings. Host and agent chart series have distinct colors and solid/dashed lines.
- Home contains a machine summary, a compact automatic-control status, and an agent list. Detailed timelines and CPU cores live under Device resources; events live under Activity.
- Manage opens automatic-control settings. Agent Details holds full process controls and the per-agent automation switch. Pause and resume remain available on desktop rows; narrow rows prioritize identity, status, and Details.
- Recovery lab, Run history, and Connections are grouped under More tools. New agent is the primary action on home.
- Measurement and policy explanations use native disclosure elements; live readings remain visible.
- Appearance follows the system. No blur is used. Reduced motion disables animation; increased contrast strengthens labels and separators.

Core palette and calculated WCAG contrast:

| Role | Light | Dark | Light / dark text contrast |
| --- | --- | --- | --- |
| Content surface | `#ffffff` | `#262628` | — |
| Main text | `#1d1d1f` | `#f5f5f7` | 16.83 / 13.87 |
| Secondary text | `#65656c` | `#ababb3` | 5.31 on canvas / 6.62 on panel |
| Accent text | `#0066cc` | `#75b6ff` | 5.57 / 7.11 |
| Healthy state | `#237744` | `#7bce99` | 5.54 / 8.01 |

Layout at regular width:

```text
Navigation | Title                                New agent
           | Machine summary                View resources
           | Automatic control status               Manage
           | Your agents · Active / All · Search
           | Agent list                           Details
```

Layout at compact width:

```text
Icon rail | Title / New agent
          | Machine summary / View resources
          | Automatic control / Manage
          | Active / All · Search
          | Agent · Status · Details
```

The design removes duplicate machine readings, breadcrumbs, status footers, recent-event previews, and the always-visible policy panel from home. Warnings and stale measurements remain explicit; simplicity does not imply that the machine is healthy.

Verification: production TypeScript/Vite build; browser checks of resource navigation, the More tools disclosure, automatic-control settings, agent search, dialog dismissal, and inspection. At 390px, home fits without horizontal scrolling. Server-rendered assertions cover normal readings, memory warnings, critical memory, high CPU, stale/disconnected observations, Linux stalls, disabled automation, and an automatic pause with a resume action. The palette was checked in light and dark appearances during the visual redesign. No agent launches or process-control actions were invoked during visual checks.

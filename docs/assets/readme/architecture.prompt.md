A clean, isometric-style architecture diagram on a dark background (#0d1117).

Four layers, left to right, connected by glowing arrows:

**Layer 1 — Data Sources** (far left):
A vertical stack of small rounded-square icons with soft glow:
- Spotify (green #1db954 circle with sound waves)
- Chrome/Google (red-yellow-blue-green circle)
- GitHub (white octocat silhouette)
- Browser Extension (puzzle piece icon, cyan outline)
- Local Files (folder icon, white outline)
Label: "Data Sources" in small white text below.

**Layer 2 — EgoGraph Pipelines** (center-left):
A tall rounded rectangle in dark blue (#0f1923) with a bright cyan (#00d4ff) glowing border.
Inside, a vertical flow of four steps connected by downward arrows:
- Top: "Scheduler" with a clock icon
- "Collector" with a download-arrow icon
- "Transform" with a gear icon
- Bottom: "Parquet on R2" with a database cylinder icon
Below the box: a small "SQLite" badge indicating job/lock state management.
Label: "EgoGraph Pipelines" below in bold white (#00d4ff tint).

**Layer 3 — EgoGraph Backend** (center):
A medium rounded rectangle in dark blue (#0f1923) with a cyan (#00d4ff) border (slightly dimmer than Pipelines).
Inside, a "Data API" label at top, with icons below:
- A tool-wrench icon with "Tool Use" text
- A DuckDB bee icon with "DuckDB" text
- A small "MCP" badge in the bottom-right corner of the box (subtle, indicating future direction)
Label: "EgoGraph Backend" below.

**Layer 4 — EgoPulse** (right):
A large rounded rectangle in dark purple (#1a0f23) with a bright magenta (#c084fc) glowing border.
Inside, an AI brain icon with neural network lines at the top.
Below it, four interface icons in a row:
- Terminal window (">_")
- Globe/browser icon (Web UI)
- Discord controller icon
- Telegram paper-plane icon
Label: "EgoPulse" below in bold white (#c084fc tint).

**Arrows and connections:**
- Solid cyan arrows: Sources → Pipelines → Backend (left to right data flow)
- A bidirectional dashed magenta arrow: Backend ↔ EgoPulse (EgoPulse queries data via Backend API, future MCP)
- A bidirectional solid magenta arrow connects EgoPulse back to a "Mobile App (Android)" icon at the bottom-right corner
- The EgoPulse box has a small "systemd" badge at the bottom edge

Style: Flat vector design with subtle neon glow on borders. No gradients except the glow effect. Clean lines, generous spacing. Developer-documentation aesthetic. No photorealism. Dark mode optimized.
Aspect ratio: 16:9.
# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Theming

### Theme
A named, self-consistent skin for the terminal UI: a semantic style palette plus an emblem, a title, a tagline, and a border colour, all bundled under one name (`tetris`, `kirby`, `zelda`, `metroid`). Selecting a theme re-skins the entire interface at once, because every UI element references styles by role rather than by colour.

### Semantic palette
The set of named style roles a Theme defines — brand, accent, info, success, warn, danger, muted, value, path — each mapped to a concrete colour/style. UI code names the role, never the colour, so a role means the same thing across the app and swapping the Theme is the only thing that changes appearance.

### Emblem
The pixel-art shape drawn in a Theme's header banner; each Theme has exactly one. Emblems are original generic geometry (a block stack, a star, a triangle), not reproductions of copyrighted characters.

Every emblem row must be symmetric with no leading or trailing padding: the header centres each row independently, so any edge whitespace used for positioning is discarded and the shape shears. Inherently asymmetric art is produced on an absolute pixel grid (SVG) instead of as centred text.

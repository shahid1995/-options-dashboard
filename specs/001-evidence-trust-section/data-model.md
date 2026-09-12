# Data Model: Evidence & Trust Section Content

## Entity: EvidenceTrustSectionContent

**Purpose**: Static content for the public Home page evidence & trust section.

**Source of truth**: `frontend/components/public/EvidenceTrustContent.js`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `eyebrow` | string | Yes | Short eyebrow label (e.g., "EVIDENCE & TRUST") |
| `title` | string | Yes | Section headline |
| `description` | string | Yes | Primary explanation paragraph |
| `points` | Array<Point> | Yes | 3-4 evidence/trust display points |
| `disclaimer` | string | Yes | Risk/uncertainty disclaimer text |
| `ctaLabel` | string | Yes | CTA button label |
| `ctaHref` | string | Yes | Destination path |

## Sub-entity: Point

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Point heading |
| `body` | string | Yes | Point description |

## Validation Rules

- `eyebrow` must be non-empty
- `title` must be non-empty
- `description` must be non-empty
- `points` array must contain at least 2 items
- `ctaHref` must be a valid path string starting with `/`

## Constraints

- Content must NOT claim guaranteed accuracy or live trading capability
- Content must NOT include technical jargon in trust messaging
- Content must reinforce paper-trading boundary
- Content must acknowledge uncertainty/risk in options markets

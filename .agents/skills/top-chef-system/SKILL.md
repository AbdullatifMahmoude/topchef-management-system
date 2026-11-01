---
name: top-chef-system
description: Route engineering work across the Top Chef FastAPI system, bundled backoffice, public menu site, and local print agent. Use when diagnosing, changing, testing, or deploying this project.
---

# Top Chef source map

The working project spans this `implementation` repository and sibling `../menu`. Begin with the nearest repository `AGENTS.md` and current Git status in each affected repository. This map is based on source inspection; recheck changed code and never assume local migrations or deployments are applied remotely.

## Pick the smallest relevant reference

- API, data, auth, workers, backoffice, print agent, or deployment boundary: read [system architecture](references/system-architecture.md).
- Public site, checkout, customer account, live menu, or a shared request/response: read [customer site](references/customer-site.md) and the affected backend router/schema/service.
- Tests, migrations, release checks, or deciding what evidence establishes a change: read [verification](references/verification.md).

## Cross-repository invariant

The public menu calls the FastAPI API directly. A change to menu, offers, pricing, orders, customer auth, settings, comments, or WebSocket messages can require coordinated edits in both repositories. Search callers and tests before changing those contracts. Financial, inventory, identity, and production-data work requires task-specific verification beyond this map.

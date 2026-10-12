# P as code software

This repository owns reusable validation, mapping, bindings, deployment and audit
code. Independent declaration repositories own instance contracts and evidence.
Keep instance declarations, credentials and deployment state outside this repo
and its images. Use pinned containers for Python tooling. Preserve the existing
schema dialects; packaging does not establish cross-dialect execution support.

Offline workers are networkless and read-only except explicit outputs. Deployment
jobs receive only the selected target's credentials, bindings and private state.
No ordinary worker receives a Docker socket. Naming registry writes retain their
native human approval. No live apply, publication or remote creation is implied
by software/package maintenance. Run existing validation/MCP and execution suites
in the built image with an explicit read-only input fixture.

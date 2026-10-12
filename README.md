# P as code software

Reusable validation, Jira shape mapping, binding generation, deployment and audit
code extracted from ControlPlane. This independent local repository is the `pascode` software source owned by
`tarskisworld`. It does not replace any instance declaration repository. No GitHub
repository was created, and no source was pushed during extraction.

The Dockerfile pins Python, locked Python dependencies and Terraform 1.14.4 by
digest. It contains no declarations, credentials, state, naming database or Docker
socket. `bin/pascodectl` is the host launcher; set `PASCODE_IMAGE` to the immutable
image ID/digest. Normal commands run packaged code, with no source bind mount.
An explicit development build can be made with `docker build --iidfile IMAGE_ID .`.
The environment integration installs the launcher by content hash and pins the image.

Commands retain validate/map/bindings/plan/apply/verify and positional arguments.
Offline work is networkless. Deployment Python and Terraform jobs receive only
selected credentials/bindings and the private work directory. Host locking still
protects that directory. Terraform is containerized by default; an explicit
`PASCODE_TERRAFORM_BINARY` retains the existing host-binary compatibility contract.
State must remain outside Git. No automatic reconciliation is introduced.

The read-only MCP deliberately retains the existing BRB/CDT target interface.
Environment configuration supplies their mounts. MainSystem uses JSON text valid
as YAML with JSON schemas; BRB/CDT use their existing YAML schema dialect. Packaging
does not make those dialects execution-compatible or resolve missing schemas.

Existing tests: `/app/tests.py`, `/app/mcp_tests.py`, `/runtime/tests.py`,
`/runtime/adapter_tests.py`, `/runtime/deployment_tests.py`. Execution tests consume
an explicit declaration fixture mounted read-only at `/inputs`. They make no live
Jira calls. `worker.py` CLI uses `--root` and `--schema-root`; `runner.py` implements
offline validate/map. Persistent state and historical instance evidence remain
with their owning environment/declaration repositories.

# Security policy

This repository is a research example, not a hardened production service. Do not deploy its operational workers against untrusted event producers or expose Redis publicly.

The operational event payload contains a local artifact path. Workers currently read the referenced path from their filesystem. **Treat the event stream as trusted** until path confinement, authentication, and authorization are implemented. A SHA-256 checksum verifies content identity; it does not authorize filesystem access.

Model promotion currently accepts caller-supplied evaluation metadata and an approval flag. It does not independently authenticate an external validation or approval decision. Keep this feature limited to controlled research environments.

Report security issues privately to the repository maintainer through GitHub's private vulnerability reporting feature, if enabled. Otherwise use a private contact channel; do not post exploit details in public issues.

Never include tokens, private datasets, host paths, or personal data in bug reports.

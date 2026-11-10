# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Report them privately through GitHub:
**Security → Report a vulnerability** on this repository (private vulnerability reporting). Include the
affected version, steps to reproduce and the impact you expect. You should get an answer within a week.

## Supported versions

| Version | Supported |
| :--- | :--- |
| 2.x (current `main` and `v2.*` tags) | yes |
| 1.x (original course demo) | no |

## Security model in short

* **Agent**: read-only RBAC by default, with no access to Secrets or ConfigMaps. Write access comes only with
  `rbac.allowRemediation=true`, and every change still needs a dry-run, approval by a second operator and the
  change window.
* **Credentials**: agent tokens are shown once and stored only as SHA-256 hashes. Passwords use PBKDF2-SHA256
  with 600k iterations. JWTs are short-lived, and roles are re-read on every request.
* **Audit**: all logins, registry changes and remediation steps are hash-chained. Run
  `GET /api/v1/audit/verify` to detect edited or deleted events.
* **Containers**: non-root, read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`.

See [docs/architecture.md](docs/architecture.md#security) for details. When deploying, set
`FINOPS_JWT_SECRET`, change the bootstrap admin password after first sign-in, and put the UI and API behind TLS
(`ingress.tls`).

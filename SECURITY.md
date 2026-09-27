# Security policy

Do not commit production `.1CD`, `.mpdb`, SQLite/database backups, private
keys, access tokens, or user exports. CI rejects common private database
extensions and obvious credential formats.

For a suspected vulnerability, use a private GitHub security advisory for this
repository rather than opening a public issue with exploit details or secrets.

Dependency vulnerabilities are checked in Windows CI with `pip-audit`.
Runtime RPC is intended for loopback/private trusted networks unless an
authenticated reverse proxy is placed in front of it.

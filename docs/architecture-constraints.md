# Architecture constraints

These items can look like omissions during a review, but are deliberate
constraints rather than deferred work.

- `.dockerignore` is part of the production boundary because the Dockerfile
  copies the repository. Keep new large top-level development directories out
  of the image.
- PHP crawler progress is human-readable command output. A Loki `level` label
  is present only when a line contains an explicit severity; no dashboard panel
  depends on it.
- Characterisation goldens cannot be regenerated because the Python reference
  implementation has been removed. A failing golden is a regression to explain,
  not a fixture to refresh.
- `SyntheticShop` is frozen with those goldens. Tests that need other state add
  it transactionally.
- The former live cross-stack crawl comparison cannot be restored. Parser,
  persistence, discovery, and API characterisation tests preserve its stable
  regression coverage; live-site drift belongs in monitoring.

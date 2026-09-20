# Optional Live Integration Testing

No live GitLab test is enabled by default. The normal suite uses fixtures and
temporary local Git repositories and performs no request to a user server.

## Contract

Future live tests must use the pytest marker `live` and skip unless every
required read-only variable is explicitly set:

- `GL_GROUPSYNC_LIVE_URL`: disposable GitLab base URL;
- `GL_GROUPSYNC_LIVE_ROOT_GROUP`: dedicated root full path or numeric ID;
- `GL_GROUPSYNC_LIVE_TOKEN`: short-lived read-only token;
- `GL_GROUPSYNC_LIVE_EXPECTED_VERSION`: exact expected server version, recorded
  before capability claims are updated.

Run only the explicit marker:

```console
GL_GROUPSYNC_LIVE_URL=https://gitlab-disposable.example \
GL_GROUPSYNC_LIVE_ROOT_GROUP=groupsync-fixture \
GL_GROUPSYNC_LIVE_TOKEN='...' \
GL_GROUPSYNC_LIVE_EXPECTED_VERSION='X.Y.Z' \
uv run pytest -m live
```

The repository currently contains no enabled live test because no disposable
instance/version was provided. Any future live test must be read-only by default:
GET/query discovery, capability probes, and cloning dedicated fixtures are
allowed; creating, editing, closing, or deleting groups, projects, issues,
comments, wiki pages, or repository refs is forbidden.

Mutation setup is a separate activity, not implied by `-m live`. It requires a
disposable dedicated instance plus separate explicit authorization documented in
the active Backlog task. A user or production server must never be populated with
fixture issues/comments. Do not introduce a generic "allow mutation" variable
that could accidentally authorize an arbitrary configured server.

After an authorized run, record the exact observed GitLab version, edition and
license-relevant capabilities, fixture setup, and pass/failure evidence in
`docs/CAPABILITIES.md`. Never replace a missing version with "latest".

# GitLab Groupsync


[![PyPI](https://img.shields.io/pypi/v/gitlab_groupsync.svg)](https://pypi.python.org/pypi/gitlab_groupsync)

[![CI](https://github.com/JNevrly/gitlab_groupsync/actions/workflows/ci.yml/badge.svg)](https://github.com/JNevrly/gitlab_groupsync/actions/workflows/ci.yml)






Tool for syncing repositories, wikis and work item from GitLab groups (and subgroups). Useful for offffline agentic search.


* Free software: MIT license


## Installation

```console
$ pip install gitlab_groupsync
```

## Features

* TODO


## Task Management

This project uses [Backlog.md](https://github.com/MrLesk/Backlog.md). Its
configuration is in `backlog/config.yml`, and task files are stored in
`backlog/tasks/` with zero-padded IDs such as `TASK-001` and filenames such as
`task-001 - Describe-the-work.md`. The agent workflow is documented in
`AGENTS.md`.

```console
$ backlog task create "Describe the work"
$ backlog board
```


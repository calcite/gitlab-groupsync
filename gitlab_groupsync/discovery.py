"""Generated inventory catalog merge and atomic persistence."""

import os
import tempfile
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from gitlab_groupsync.gitlab_api import DiscoveryError, Inventory, InventoryObject


def refresh_catalog(
    config_path: str | Path,
    inventory: Inventory,
    *,
    replace_root: bool = False,
) -> None:
    """Merge a complete inventory into the persisted YAML and atomically replace it."""
    if not inventory.complete:
        raise DiscoveryError("refusing to persist an incomplete inventory")
    path = Path(config_path)
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    try:
        with path.open(encoding="utf-8") as source:
            document = yaml.load(source)
    except (OSError, YAMLError) as exc:
        raise DiscoveryError("could not read configuration for refresh") from exc
    if not isinstance(document, MutableMapping):
        raise DiscoveryError("configuration YAML must contain a mapping")

    old_inventory = document.get("inventory")
    if old_inventory is None:
        old_inventory = {}
    if not isinstance(old_inventory, Mapping):
        raise DiscoveryError("persisted inventory must be a mapping")
    old_root = old_inventory.get("root_group")
    if (
        isinstance(old_root, Mapping)
        and old_root.get("id") is not None
        and old_root.get("id") != inventory.root_group.id
        and not replace_root
    ):
        raise DiscoveryError(
            "discovered root group ID differs; rerun with --replace-root to approve"
        )

    document["inventory"] = _merged_inventory(old_inventory, inventory)
    _atomic_dump(path, document, yaml)


def inventory_from_config(config: Mapping[str, Any]) -> Inventory | None:
    """Convert a validated generated catalog to immutable values."""
    value = config["inventory"]
    root = value["root_group"]
    if root is None:
        return None
    return Inventory(
        InventoryObject(root["id"], root["full_path"]),
        tuple(
            InventoryObject(item["id"], item["full_path"]) for item in value["groups"]
        ),
        tuple(
            InventoryObject(item["id"], item["full_path"]) for item in value["projects"]
        ),
        complete=True,
    )


def _merged_inventory(old: Mapping[str, Any], inventory: Inventory) -> dict[str, Any]:
    old_groups = {
        item["id"]: item
        for item in old.get("groups", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), int)
    }
    old_projects = {
        item["id"]: item
        for item in old.get("projects", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), int)
    }
    groups = [
        {
            "id": item.id,
            "full_path": item.full_path,
            "wiki": bool(old_groups.get(item.id, {}).get("wiki", False)),
        }
        for item in sorted(inventory.groups)
    ]
    projects = [
        {
            "id": item.id,
            "full_path": item.full_path,
            "repository": bool(old_projects.get(item.id, {}).get("repository", False)),
            "wiki": bool(old_projects.get(item.id, {}).get("wiki", False)),
            "work_items": bool(old_projects.get(item.id, {}).get("work_items", False)),
        }
        for item in sorted(inventory.projects)
    ]
    return {
        "root_group": {
            "id": inventory.root_group.id,
            "full_path": inventory.root_group.full_path,
        },
        "groups": groups,
        "projects": projects,
    }


def _atomic_dump(path: Path, document: Any, yaml: YAML) -> None:
    temporary: str | None = None
    try:
        mode = path.stat().st_mode & 0o7777
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            os.fchmod(output.fileno(), mode)
            yaml.dump(document, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, YAMLError) as exc:
        raise DiscoveryError("could not atomically refresh configuration") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

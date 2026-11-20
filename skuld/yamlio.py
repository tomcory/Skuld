"""
YAML as Skuld reads it: safe, and refusing a mapping that names a key twice.

PyYAML's `safe_load` keeps the last of two equal keys. A second `compatible_versions:` in an `assessment.yaml`
silently replaced the first, and qwen's Remini went from 351 concerns to 1 (`plan/archive/POST_PAPER_FIXES.md` 3). Every YAML
Skuld reads goes through `load`.
"""

import yaml


class DuplicateKeyError(yaml.constructor.ConstructorError):
    """A mapping names a key twice."""


class _StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    seen: dict = {}
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise DuplicateKeyError(
                "while constructing a mapping",
                node.start_mark,
                f"the key {key!r} is given twice (first at line {seen[key].line + 1})",
                key_node.start_mark,
            )
        seen[key] = key_node.start_mark
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load(text: str):
    """The YAML document in `text`, refused (DuplicateKeyError, a yaml.YAMLError) if a mapping repeats a key."""
    return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - a SafeLoader subclass

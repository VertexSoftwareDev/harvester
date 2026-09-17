"""A small, typed plugin registry backed by Python entry points.

Built-in plugins register themselves with a decorator. Third-party packages can
add more without touching this code base by declaring an entry point, e.g.::

    [project.entry-points."harvester.exporters"]
    sheets = "my_package.exporters:GoogleSheetsExporter"
"""

import difflib
import logging
from collections.abc import Callable, Iterator
from importlib.metadata import entry_points

logger = logging.getLogger(__name__)


class PluginNotFoundError(LookupError):
    """Raised when a plugin name is not registered."""

    def __init__(self, kind: str, name: str, available: list[str]) -> None:
        message = f"Unknown {kind} {name!r}. Available: {', '.join(available) or 'none'}."
        if matches := difflib.get_close_matches(name, available, n=1):
            message += f" Did you mean {matches[0]!r}?"
        super().__init__(message)
        self.kind = kind
        self.name = name


class Registry[T]:
    """Name -> object mapping with lazy entry-point discovery."""

    def __init__(self, kind: str, *, entry_point_group: str | None = None) -> None:
        self.kind = kind
        self._group = entry_point_group
        self._items: dict[str, T] = {}
        self._entry_points_loaded = False

    def register(self, name: str) -> Callable[[T], T]:
        """Decorator form of :meth:`add`."""

        def decorator(obj: T) -> T:
            self.add(name, obj)
            return obj

        return decorator

    def add(self, name: str, obj: T, *, replace: bool = False) -> None:
        if name in self._items and not replace:
            raise ValueError(f"{self.kind} {name!r} is already registered")
        self._items[name] = obj

    def get(self, name: str) -> T:
        self._load_entry_points()
        try:
            return self._items[name]
        except KeyError:
            raise PluginNotFoundError(self.kind, name, self.names()) from None

    def names(self) -> list[str]:
        self._load_entry_points()
        return sorted(self._items)

    def __contains__(self, name: object) -> bool:
        self._load_entry_points()
        return name in self._items

    def __iter__(self) -> Iterator[tuple[str, T]]:
        return ((name, self._items[name]) for name in self.names())

    def __len__(self) -> int:
        self._load_entry_points()
        return len(self._items)

    def _load_entry_points(self) -> None:
        if self._entry_points_loaded or self._group is None:
            return
        self._entry_points_loaded = True
        for ep in entry_points(group=self._group):
            if ep.name in self._items:
                logger.warning("Ignoring %s plugin %r: name already registered", self.kind, ep.name)
                continue
            try:
                self._items[ep.name] = ep.load()
            except Exception:
                logger.exception("Failed to load %s plugin %r (%s)", self.kind, ep.name, ep.value)

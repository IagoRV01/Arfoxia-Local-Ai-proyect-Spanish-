"""Default project location, not a sandbox for owner-authorized PC commands."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


def default_workspace_directory() -> str:
    return str(Path.home() / "Arfoxia")


def workspace_root(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("La carpeta de trabajo local no es válida.")
    root = Path(value)
    if not root.is_absolute() or ".." in root.parts or root.parent == root:
        raise ValueError("La carpeta de trabajo debe ser absoluta y no ser una raíz del disco.")
    if value.replace("/", "\\").startswith(("\\\\", "\\??\\", "\\device\\")):
        raise ValueError("La carpeta de trabajo debe ser local, no una ruta de red/dispositivo.")
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("La carpeta de trabajo no puede ser un enlace o unión de directorios.")
    return root.resolve()


def project_path(value: str, root: Path) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("Indica una ruta válida dentro de la carpeta de trabajo.")
    value = os.path.expandvars(value.strip())
    path = Path(value)
    if path.is_absolute():
        # Explicit absolute paths retain the existing action policy/validation.
        return value
    if PureWindowsPath(value).drive or ".." in path.parts or value.startswith(("\\", "/")):
        raise ValueError("La ruta relativa no puede salir de la carpeta de trabajo.")
    candidate = root / path
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("La ruta relativa no puede salir de la carpeta de trabajo mediante enlaces.")
    return str(candidate)  # Keep links visible to the existing file validator.


def workspace_arguments(action: str, arguments: dict, directory: str) -> dict:
    args = dict(arguments)
    if action not in {"file_operation", "list_directory", "read_file", "search_files", "run_python", "run_powershell"}:
        return args
    root = workspace_root(directory)
    if action in {"run_python", "run_powershell"}:
        args["working_directory"] = project_path(args.get("working_directory", str(root)), root)
    else:
        if action in {"list_directory", "search_files"} and "path" not in args:
            args["path"] = str(root)
        for key in ("path", "destination") if action == "file_operation" else ("path",):
            if key in args:
                args[key] = project_path(args[key], root)
    return args

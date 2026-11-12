"""Generate exact payload/deletion lists: uninstall never recursively removes data."""

import ast
from pathlib import Path
import shutil


def escape(value):
    return str(value).replace("$", "$$").replace('"', '$\\"')


def main():
    root = Path(__file__).resolve().parents[1]
    binary = root / "dist" / "DC-Assistant"
    if not (binary / "DC-Assistant.exe").is_file():
        raise ValueError("Build the Windows app first")
    for name in ("README.md", "CHANGELOG.md"):
        shutil.copyfile(root / name, binary / name)
    module = ast.parse((root / "dc_assistant/__init__.py").read_text(encoding="utf-8"))
    version = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    )
    generated = root / "installer" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "version.nsh").write_text(
        f'!define APP_VERSION "{version}"\n', encoding="utf-8-sig"
    )
    files = sorted(path for path in binary.rglob("*") if path.is_file())
    files.sort(key=lambda path: (path.name != "DC-Assistant.exe", str(path)))
    install = []
    uninstall = []
    folders = set()
    for path in files:
        relative = path.relative_to(binary)
        if path.suffix.lower() in {".sqlite3", ".db", ".xlsx", ".pdf", ".dwg"}:
            raise ValueError("A user-data file is present in the application payload")
        destination = str(relative.parent).replace("/", "\\")
        install.append(f'SetOutPath "$INSTDIR\\{escape(destination)}"')
        install.append(f'File "..\\dist\\DC-Assistant\\{escape(relative)}"')
        uninstall.append(f'Delete "$INSTDIR\\{escape(relative)}"')
        for parent in relative.parents:
            if str(parent) != ".":
                folders.add(parent)
    for folder in sorted(
        folders, key=lambda value: (len(value.parts), str(value)), reverse=True
    ):
        uninstall.append(f'RMDir "$INSTDIR\\{escape(folder)}"')
    (generated / "payload.nsh").write_text(
        "\n".join(install) + "\n", encoding="utf-8-sig"
    )
    (generated / "uninstall-files.nsh").write_text(
        "\n".join(uninstall) + "\n", encoding="utf-8-sig"
    )
    print(f"Prepared {len(files)} application files for Setup {version}")


if __name__ == "__main__":
    main()

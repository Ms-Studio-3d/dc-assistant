"""Acquire the official portable NSIS compiler inside this project only."""

import hashlib
import io
from pathlib import Path
import sys
from urllib.request import Request, urlopen
import zipfile

VERSION = "3.13"
URL = f"https://downloads.sourceforge.net/project/nsis/NSIS%203/{VERSION}/nsis-{VERSION}.zip"
SHA256 = "ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8"


def main():
    target = Path(sys.argv[1]).resolve()
    target.mkdir(parents=True, exist_ok=True)
    archive_path = target / f"nsis-{VERSION}.zip"
    if archive_path.exists():
        raw = archive_path.read_bytes()
    else:
        with urlopen(
            Request(URL, headers={"User-Agent": "DC-Assistant-build"}), timeout=60
        ) as response:
            raw = response.read()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("NSIS download digest differs from the verified release")
    archive_path.write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for item in archive.infolist():
            destination = target / item.filename
            destination.resolve().relative_to(target)
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(item))
    print(target / f"nsis-{VERSION}" / "makensis.exe")


if __name__ == "__main__":
    main()

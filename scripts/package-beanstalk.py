"""Create an ECR bundle and reviewed host hooks; never include .env or keys."""

import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_uri", help="Full ECR image URI including a version tag")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    descriptor = {
        "AWSEBDockerrunVersion": "1",
        "Image": {"Name": args.image_uri, "Update": "true"},
        "Ports": [{"ContainerPort": "8000"}],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w") as bundle:
        bundle.writestr("Dockerrun.aws.json", json.dumps(descriptor, indent=2))
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "scripts/setup-origin-tls.sh",
            ".platform/hooks/postdeploy/50_origin_tls.sh",
            ".platform/confighooks/postdeploy/50_origin_tls.sh",
        ):
            source = root / relative
            if source.is_symlink():
                raise ValueError(f"Refusing symlink in deployment bundle: {relative}")
            bundle.write(source, relative)


if __name__ == "__main__":
    main()

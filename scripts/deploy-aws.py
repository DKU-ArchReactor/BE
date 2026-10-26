"""Deploy reviewed local code to the existing Blank Canvas Beanstalk environment.

Uses the dedicated profile, rejects another account, and never uploads .env.
Initial infrastructure provisioning is defined in infrastructure/*.yml.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "242925688392"
REGION = "ap-northeast-2"
BUCKET = f"elasticbeanstalk-{REGION}-{ACCOUNT}"
REPOSITORY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/capstone/archreactor"
HTTPS_ENDPOINT = "https://d1j3nkcez6kncs.cloudfront.net"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="archreactor-new")
    parser.add_argument("--aws", default=shutil.which("aws") or "aws")
    args = parser.parse_args()

    def aws(*parts):
        result = subprocess.run(
            [args.aws, "--profile", args.profile, "--region", REGION,
             "--output", "json", "--no-cli-pager", *parts],
            check=True, text=True, capture_output=True, cwd=ROOT,
        )
        return json.loads(result.stdout) if result.stdout.strip() else {}

    if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise SystemExit(f"Refusing to deploy: expected AWS account {ACCOUNT}")
    envs = aws("elasticbeanstalk", "describe-environments", "--environment-names",
               "archreactor-core")["Environments"]
    if len(envs) != 1 or envs[0]["Status"] != "Ready":
        raise SystemExit("Beanstalk environment must exist and be Ready")
    package = json.loads(subprocess.check_output(
        [sys.executable, "scripts/package-source.py"], cwd=ROOT, text=True,
    ))
    # A run suffix supports intentional rebuilds of the same source with newer base images.
    tag = f"core-{package['sha256'][:16]}-{int(time.time())}"
    source_key = f"source/{tag}.zip"
    aws("s3api", "put-object", "--bucket", BUCKET, "--key", source_key,
        "--body", package["file"], "--server-side-encryption", "AES256")
    build = aws("codebuild", "start-build", "--project-name", "archreactor-image-build",
                "--source-location-override", f"{BUCKET}/{source_key}",
                "--environment-variables-override", json.dumps([
                    {"name": "IMAGE_TAG", "value": tag, "type": "PLAINTEXT"},
                ]))["build"]
    print(f"Build: {build['id']}", flush=True)
    deadline = time.monotonic() + 3600
    previous = None
    while time.monotonic() < deadline:
        build = aws("codebuild", "batch-get-builds", "--ids", build["id"])["builds"][0]
        state = (build["buildStatus"], build["currentPhase"])
        if state != previous:
            print("Build:", *state, flush=True)
            previous = state
        if build["buildStatus"] == "SUCCEEDED":
            break
        if build["buildStatus"] != "IN_PROGRESS":
            raise SystemExit("Build failed. Review the CodeBuild CloudWatch log.")
        time.sleep(15)
    else:
        raise SystemExit("Build wait timed out; inspect CodeBuild before retrying.")
    image = f"{REPOSITORY}:{tag}"
    aws("ecr", "describe-images", "--repository-name", "capstone/archreactor",
        "--image-ids", f"imageTag={tag}")
    subprocess.run([sys.executable, "scripts/package-beanstalk.py", image,
                    "dist/beanstalk.zip"], cwd=ROOT, check=True)
    bundle_key = f"archreactor/{tag}.zip"
    aws("s3api", "put-object", "--bucket", BUCKET, "--key", bundle_key,
        "--body", "dist/beanstalk.zip", "--server-side-encryption", "AES256")
    aws("elasticbeanstalk", "create-application-version", "--application-name",
        "archreactor", "--version-label", tag, "--source-bundle",
        json.dumps({"S3Bucket": BUCKET, "S3Key": bundle_key}))
    aws("elasticbeanstalk", "update-environment", "--environment-name",
        "archreactor-core", "--version-label", tag)
    deadline = time.monotonic() + 2400
    previous = None
    while time.monotonic() < deadline:
        env = aws("elasticbeanstalk", "describe-environments", "--environment-names",
                  "archreactor-core")["Environments"][0]
        state = (env["Status"], env.get("Health"), env.get("VersionLabel"))
        if state != previous:
            print("Environment:", *state, flush=True)
            previous = state
        if state == ("Ready", "Green", tag):
            with urllib.request.urlopen(HTTPS_ENDPOINT + "/", timeout=20) as response:
                if response.status != 200 or json.load(response).get("status") != "ok":
                    raise SystemExit("HTTPS endpoint health check failed")
            print(f"Healthy deployment: {HTTPS_ENDPOINT}/", flush=True)
            return
        if env["Status"] in ("Terminated", "Terminating"):
            raise SystemExit("Environment terminated during deployment")
        time.sleep(15)
    raise SystemExit("Deployment did not become healthy; inspect Beanstalk events.")


if __name__ == "__main__":
    main()

"""Rebuild the FlareSolverr container from scratch, with caps on it.

`docker restart` keeps the same container, so Chrome's temp files and an
unrotated log kept piling up inside it. By 16 Nov 2026 Docker's disk was
238 GB and the Mac had 10 GB free. A fresh container each time throws all of
that away, and the log options cap what a single container can grow to.

This also covers the container being missing altogether (after a Docker
"Clean up data" or a new Mac), which `docker restart` cannot fix.

Settings, all overridable from the environment:
  FLARESOLVERR_CONTAINER  container name, default "flaresolverr"
  FLARESOLVERR_IMAGE      image, default the :latest already pulled (3.5.2 on 16 Nov)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

NAME = os.environ.get("FLARESOLVERR_CONTAINER", "flaresolverr")
IMAGE = os.environ.get("FLARESOLVERR_IMAGE", "ghcr.io/flaresolverr/flaresolverr:latest")
PORT = "8191"

# The exact command, for doing it by hand:
#   docker rm -f flaresolverr
#   docker run -d --name flaresolverr --restart unless-stopped -p 8191:8191 \
#     --log-opt max-size=10m --log-opt max-file=3 ghcr.io/flaresolverr/flaresolverr:latest
RUN_ARGS = ["run", "-d", "--name", NAME, "--restart", "unless-stopped",
            "-p", f"{PORT}:{PORT}",
            "--log-opt", "max-size=10m", "--log-opt", "max-file=3",
            IMAGE]


def docker_path() -> str | None:
    return shutil.which("docker") or next(
        (p for p in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker",
                     "/Applications/Docker.app/Contents/Resources/bin/docker")
         if os.path.exists(p)), None)


def _engine_up(docker: str) -> bool:
    try:
        return subprocess.run([docker, "info"], capture_output=True,
                              timeout=20).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def recreate(log=print) -> bool:
    """Open Docker Desktop if the engine is down, then remove and recreate
    the container. True once `docker run` succeeded (the caller still waits
    for it to answer). Never raises."""
    docker = docker_path()
    if not docker:
        log("  docker not found on this Mac")
        return False
    if not _engine_up(docker):
        log("  Docker engine not running, opening Docker Desktop")
        subprocess.run(["open", "-a", "Docker"], capture_output=True, timeout=20)
        for _ in range(36):  # up to three minutes for a cold start
            time.sleep(5)
            if _engine_up(docker):
                break
        else:
            log("  Docker engine still not up after three minutes")
            return False
    try:
        subprocess.run([docker, "rm", "-f", NAME], capture_output=True, timeout=60)
        done = subprocess.run([docker, *RUN_ARGS], capture_output=True, text=True,
                              timeout=600)  # first run pulls the image
    except Exception as exc:  # noqa: BLE001
        log(f"  could not recreate FlareSolverr ({type(exc).__name__})")
        return False
    if done.returncode != 0:
        log(f"  docker run failed: {(done.stderr or '').strip()[:200]}")
        return False
    log("  FlareSolverr container recreated")
    return True

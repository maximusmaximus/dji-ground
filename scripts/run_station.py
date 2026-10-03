"""Back-compat shim. Prefer `uv run dji-station` (see README)."""

from dji_ground.station import cli

if __name__ == "__main__":
    cli()

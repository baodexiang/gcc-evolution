"""Compatibility CLI entrypoint for packaged gcc-evo."""

from .gcc_evo import cli


def main():
    """Package entrypoint used by setup.py / pyproject.toml."""
    cli(standalone_mode=True)


if __name__ == "__main__":
    main()

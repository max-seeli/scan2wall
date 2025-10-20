"""CLI interface for scan2wall package.

Usage:
    python -m scan2wall    # Show version and basic info
"""


def main():
    """Main CLI entry point."""
    from scan2wall import main as show_info
    show_info()


if __name__ == "__main__":
    main()

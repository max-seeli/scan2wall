"""CLI interface for scan2wall package.

Usage:
    python -m scan2wall --check    # Display and validate path configuration
    python -m scan2wall             # Show version and basic info
"""

import sys


def main():
    """Main CLI entry point."""
    if "--check" in sys.argv:
        # Display full path configuration and validation
        from scan2wall.utils.paths import print_path_configuration
        print_path_configuration()
    else:
        # Show basic version info
        from scan2wall import main as show_info
        show_info()


if __name__ == "__main__":
    main()

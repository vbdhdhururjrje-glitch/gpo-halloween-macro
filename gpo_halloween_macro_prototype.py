"""Backward-compatible launcher for the modular application."""

from app.main import main


if __name__ == "__main__":
    raise SystemExit(main())

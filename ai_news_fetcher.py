"""Legacy entry point — delegates to the new pipeline."""

from ai_news.pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
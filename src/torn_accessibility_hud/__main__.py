"""Module entry point."""

if __name__ == "__main__":
    print("[DEBUG] __main__ entrypoint invoked", flush=True)
    from .app import main

    raise SystemExit(main())

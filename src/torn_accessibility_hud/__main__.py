"""Module entry point."""

if __name__ == "__main__":
    from .diagnostics import configure_runtime_logging, debug_log, write_startup_log

    configure_runtime_logging()
    write_startup_log("__main__ entrypoint invoked")
    debug_log("__main__ entrypoint invoked")
    from .app import main

    raise SystemExit(main())

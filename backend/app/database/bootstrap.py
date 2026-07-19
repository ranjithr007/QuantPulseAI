def bootstrap_sqlite_demo_data(engine):
    """
    Minimal startup-safe SQLite bootstrap hook.

    The app startup path imports this symbol whenever SQLite fallback mode is
    enabled. Some earlier refactor left this module empty, which breaks import
    time before the server can boot.

    For now we keep the hook as a harmless no-op so development startup works.
    Actual demo-data seeding can be reintroduced here later if needed.
    """

    return None

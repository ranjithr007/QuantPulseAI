def commit_or_rollback(db):
    try:
        if hasattr(db, "commit"):
            db.commit()
    except Exception:
        safe_rollback(db)
        raise


def flush_or_rollback(db):
    try:
        if hasattr(db, "flush"):
            db.flush()
    except Exception:
        safe_rollback(db)
        raise


def safe_rollback(db):
    if hasattr(db, "rollback"):
        db.rollback()

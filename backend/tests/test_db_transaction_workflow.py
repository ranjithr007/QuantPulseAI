from unittest.mock import Mock

import pytest

from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback


def test_commit_or_rollback_rolls_back_on_commit_error():
    db = type(
        "FakeDB",
        (),
        {
            "commit": Mock(side_effect=RuntimeError("boom")),
            "rollback": Mock(),
        },
    )()

    with pytest.raises(RuntimeError):
        commit_or_rollback(db)

    assert db.rollback.called


def test_flush_or_rollback_rolls_back_on_flush_error():
    db = type(
        "FakeDB",
        (),
        {
            "flush": Mock(side_effect=RuntimeError("boom")),
            "rollback": Mock(),
        },
    )()

    with pytest.raises(RuntimeError):
        flush_or_rollback(db)

    assert db.rollback.called

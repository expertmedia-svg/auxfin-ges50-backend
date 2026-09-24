from sqlalchemy import event
from app.services.operations import OperationQuery, operational_data
from app.services.followups import update_followups
from tests.test_followups import make_report


def test_followup_reads_are_batched(db_session):
    for i in range(30):
        ev = make_report(db_session, group=f"gr{i}.test", phone=f"2267000{i:04d}")
        update_followups(db_session, ev)
    db_session.commit()
    db_session.expire_all()
    statements = []
    def collect(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", collect)
    try:
        result = operational_data(db_session, OperationQuery(dataset="followups", scope="all",
                                                            start="2026-09-14", end="2026-09-14"))
    finally:
        event.remove(engine, "before_cursor_execute", collect)
    assert result["total"] == 30
    assert len(statements) <= 6, len(statements)

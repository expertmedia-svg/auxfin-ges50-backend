from datetime import datetime, date
from app.models.projects import Project, ProjectGroup, ProjectExpectedGroup
from app.models.whatsapp import WhatsAppGroup, WhatsAppMessage
from app.services.projects import project_dashboard
from tests.test_followups import make_report


def test_project_coverage_isolated_and_frequency(db_session):
    ev = make_report(db_session, confirmed=True)
    ev.received_at = datetime(2026, 9, 28, 12)
    project = Project(name='Projet A')
    other = Project(name='Projet B')
    group = WhatsAppGroup(name='Groupe A', whatsapp_group_external_id='123@g.us')
    db_session.add_all([project, other, group]); db_session.flush()
    db_session.add(ProjectGroup(group_id=group.id, project_id=project.id))
    db_session.add(WhatsAppMessage(whatsapp_message_id='test-projet', group_id=group.id,
        group_external_id='123@g.us', evidence_id=ev.id, message_date=ev.received_at))
    db_session.add_all([ProjectExpectedGroup(project_id=project.id, application_id=ev.application_id, business_id=ev.extraction.effective_group_id.casefold()),
                       ProjectExpectedGroup(project_id=project.id, application_id=ev.application_id, business_id='gr.absent')])
    db_session.commit()
    result = project_dashboard(db_session, project.id, date(2026,9,28), date(2026,9,29), 'daily')
    assert result['received'] == 1
    assert result['valid'] == 1
    assert result['expected'] == 4
    assert result['missing'] == 3
    assert project_dashboard(db_session, other.id, date(2026,9,28), date(2026,9,29), 'period')['received'] == 0
    result = project_dashboard(db_session, project.id, date(2026,9,28), date(2026,9,29), 'period')
    assert result['missing'] == 1

from tests.test_evidence_status_and_origin import client, auth_token  # noqa: F401


def test_import_ids_is_idempotent_and_group_conflict(client, auth_token, db_session):
    ev = make_report(db_session)
    db_session.commit()
    headers = {'Authorization': f'Bearer {auth_token}'}
    response = client.post('/api/projects', headers=headers, json={'name': 'Projet import'})
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    for expected in (2, 0):
        response = client.post(f'/api/projects/{pid}/expected', headers=headers,
            data={'application_id': ev.application_id}, files={'file': ('ids.csv', b'id\ngr1.test\nGR1.TEST\ngr2.test\n', 'text/csv')})
        assert response.status_code == 200, response.text
        assert response.json()['added'] == expected
    group = WhatsAppGroup(name='g', whatsapp_group_external_id='456@g.us')
    other = Project(name='Autre')
    db_session.add_all([group, other]); db_session.flush()
    db_session.add(ProjectGroup(group_id=group.id, project_id=other.id)); db_session.commit()
    response = client.put(f'/api/projects/{pid}/groups', headers=headers, json={'group_ids': [group.id]})
    assert response.status_code == 409


def test_project_migration_has_timestamp_defaults(tmp_path):
    import importlib.util
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from pathlib import Path
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE whatsapp_groups (id VARCHAR PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE applications (id VARCHAR PRIMARY KEY)'))
        path = Path(__file__).parents[1] / 'alembic/versions/b509280001_projects.py'
        spec = importlib.util.spec_from_file_location('project_migration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        conn.execute(text("INSERT INTO projects (id, name) VALUES ('test', 'Projet')"))
        assert conn.execute(text('SELECT created_at FROM projects')).scalar() is not None
        module.downgrade()

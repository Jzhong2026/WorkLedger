from __future__ import annotations

import json

import pytest

from workledger.services.jira_import import import_issues
from workledger.schemas import EventUpdate
from workledger.services import events


def test_incremental_import_resolves_late_parent_and_preserves_edited_summary(conn):
    parent = {'key': 'DEMO-1', 'summary': 'Parent', 'created': '2026-01-03T09:00:00+0800'}
    child = {
        'key': 'DEMO-2', 'summary': 'Child', 'created': '2026-01-04T11:20:00+0800',
        'status': {'name': 'Open'}, 'parent': {'key': 'DEMO-1'},
    }
    import_issues(conn, [child], project_key='DEMO', project_name='Demo')
    first = events.search_events(conn, jira_key='DEMO-2')[0][0]
    events.update_event(conn, first['id'], EventUpdate(summary='My summary'))

    import_issues(conn, [parent], project_key='DEMO', project_name='Demo')
    import_issues(conn, [dict(child, summary='Changed', status={'name': 'Done'})],
                  project_key='DEMO', project_name='Demo', base_url='https://example.test')

    latest = events.get_event(conn, first['id'])
    assert latest['parent_event_id'] == events.search_events(conn, jira_key='DEMO-1')[0][0]['id']
    assert latest['summary'] == 'My summary'
    assert latest['occurred_at'] == '2026-01-04 11:20:00'
    assert latest['recorded_at'] == first['recorded_at']
    assert latest['evidence_url'] == 'https://example.test/browse/DEMO-2'
    assert json.loads(latest['extra_json'])['status'] == 'Done'


def test_import_rolls_back_project_and_partial_records_when_parent_links_cycle(conn):
    issues = [
        {'key': 'DEMO-1', 'summary': 'First', 'parent': {'key': 'DEMO-2'}},
        {'key': 'DEMO-2', 'summary': 'Second', 'parent': {'key': 'DEMO-1'}},
    ]
    with pytest.raises(ValueError, match='cycle'):
        import_issues(conn, issues, project_key='DEMO', project_name='Demo')

    assert not conn.execute('SELECT id FROM projects').fetchall()
    assert events.search_events(conn)[1] == 0


def test_import_partial_older_exports_preserve_source_data_without_requiring_optional_fields(conn):
    latest = {
        'key': 'DEMO-1',
        'fields': {
            'summary': 'Latest', 'description': 'Full description',
            'created': '2026-01-02T10:30:00Z', 'updated': '2026-01-10T10:30:00Z',
        },
    }
    settings = {'project_key': 'DEMO', 'project_name': 'Demo'}
    import_issues(conn, [latest], **settings)
    old = dict(latest, summary='Old', updated='2026-01-03T10:30:00Z')
    assert import_issues(conn, [old], **settings)['unchanged'] == 1
    import_issues(
        conn, [{'key': 'DEMO-1', 'summary': 'New', 'updated': '2026-01-15T10:30:00Z'}],
        **settings,
    )

    rows, total = events.search_events(conn)
    assert total == 1
    assert rows[0]['summary'] == 'New'
    assert 'Full description' in rows[0]['detail']
    assert rows[0]['occurred_at'] == '2026-01-02 10:30:00'
    assert rows[0]['evidence_url'] is None


def test_import_stores_status_category_and_assignee_identity(conn):
    from workledger.services.jira_import import import_issues
    issue = {
        'key': 'RW-900', 'summary': 'Identity', 'created': '2026-11-01T09:00:00+0800',
        'status': {'name': 'In Progress', 'statusCategory': {'key': 'indeterminate'}},
        'assignee': {'accountId': 'acc-jason', 'displayName': 'JasonZhong'},
    }
    import_issues(conn, [issue], project_key='RW', project_name='RW')
    from workledger.services import events
    row = events.search_events(conn, jira_key='RW-900')[0][0]
    extra = json.loads(row['extra_json'])
    assert extra['status_category'] == 'indeterminate'
    assert extra['assignee_account_id'] == 'acc-jason'
    assert extra['assignee_name'] == 'JasonZhong'


def test_is_done_handles_chinese_legacy_statuses():
    from workledger.services.jira_import import is_done
    assert is_done(None, '已完成') is True
    assert is_done(None, 'Done') is True
    assert is_done(None, '已关闭') is True
    assert is_done(None, 'In Backlog') is False
    assert is_done(None, 'Acceptance') is False
    assert is_done('done', 'Whatever') is True
    assert is_done('indeterminate', '已完成') is False  # category 优先
    assert is_done(None, None) is False


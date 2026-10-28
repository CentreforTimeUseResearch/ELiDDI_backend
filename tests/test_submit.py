import json

import pytest

from app import create_app

PAYLOAD = {
    'experimentID': 'mumtime',
    'version': '1.0',
    'dayBoundary': '04:00',
    'date': '2026-10-28',
    'status': 0,
    'timelines': [[{'id': 'a', 'startOffsetMins': 0, 'endOffsetMins': 60, 'activity': 'Sleep'}]],
}


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path)
    return app.test_client()


def test_index(client):
    assert client.get('/').status_code == 200


def test_saves_payload_keyed_by_experiment_date_and_timestamp(client, tmp_path):
    response = client.post('/submit', json=PAYLOAD)

    assert response.status_code == 201
    files = list((tmp_path / 'mumtime').glob('2026-10-28_*.json'))
    assert [f.name for f in files] == [response.get_json()['saved']]
    assert json.loads(files[0].read_text(encoding='utf-8')) == PAYLOAD


def test_two_submissions_do_not_overwrite_each_other(client, tmp_path):
    client.post('/submit', json=PAYLOAD)
    client.post('/submit', json=PAYLOAD)

    assert len(list((tmp_path / 'mumtime').glob('*.json'))) == 2


def test_preflight_is_answered_with_cors_headers(client):
    response = client.options('/submit')

    assert response.status_code == 204
    assert response.headers['Access-Control-Allow-Origin'] == '*'
    assert response.headers['Access-Control-Allow-Headers'] == 'Content-Type'
    assert 'POST' in response.headers['Access-Control-Allow-Methods']


def test_post_response_has_cors_header(client):
    response = client.post('/submit', json=PAYLOAD)

    assert response.headers['Access-Control-Allow-Origin'] == '*'


@pytest.mark.parametrize('experiment_id', ['../evil', 'a/b', 'a\\b', '', 'x' * 65, 5, None])
def test_rejects_unsafe_experiment_id(client, tmp_path, experiment_id):
    response = client.post('/submit', json={**PAYLOAD, 'experimentID': experiment_id})

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('date', ['2026-13-01', '2026-02-30', '28-10-2026', '../2026-10-28', 20261028, None])
def test_rejects_invalid_date(client, tmp_path, date):
    response = client.post('/submit', json={**PAYLOAD, 'date': date})

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_rejects_missing_fields(client):
    assert client.post('/submit', json={}).status_code == 400


def test_rejects_non_json_body(client):
    response = client.post('/submit', data='experimentID=mumtime', content_type='application/x-www-form-urlencoded')

    assert response.status_code == 400


def test_rejects_json_that_is_not_an_object(client):
    assert client.post('/submit', json=[1, 2]).status_code == 400

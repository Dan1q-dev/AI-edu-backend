"""Shared fixtures for regression tests against the versioned practice API."""
from .services import save_draft, publish_draft


def configure_checklist(item, titles, user=None):
    save_draft(item, user, {'practice_type': 'checklist_practice', 'plugin_version': '1.0.0',
        'title': item.title, 'description': item.description,
        'config': {'criteria': [{'title': title, 'description': '', 'is_required': True} for title in titles]}})
    version = publish_draft(item)
    item.refresh_from_db()
    return version


def submit_checklist(client, item, checks):
    path = f'/api/v1/items/{item.short_id}/practice/'
    started = client.post(path + 'start/')
    if started.status_code != 200:
        return started
    return client.post(path, {'submission_id': started.data['submission']['id'],
                             'submission_data': {'checks': checks}}, format='json')

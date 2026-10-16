from apps.education.models import Lesson


def draft_media_ids():
    ids = set()
    for draft in Lesson.all_objects.exclude(draft_data=None).values_list('draft_data', flat=True).iterator():
        if not isinstance(draft, dict):
            continue
        for block in draft.get('blocks', []):
            if isinstance(block, dict) and isinstance(block.get('media'), int):
                ids.add(block['media'])
        for attachment in draft.get('attachments', []):
            media_id = attachment.get('media') if isinstance(attachment, dict) else attachment
            if isinstance(media_id, int):
                ids.add(media_id)
    return ids

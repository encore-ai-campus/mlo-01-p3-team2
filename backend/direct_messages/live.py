from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def user_group(user_id):
    return f'campus.dm.user.{user_id}'


def notify(user_id, conversation_id):
    # The private channel carries only a change notification, never message text.
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(user_group(user_id), {
            'type':'direct.message', 'conversationId':str(conversation_id),
        })

from fastapi import APIRouter, Request, HTTPException
from src.middleware import verify_jwt, require_role
from src.db import db, audit_event
from src.schemas.threads import (
    ThreadCreate,
    MessageCreate,
    ChannelCreate,
    ThreadMemberCreate,
    PresenceUpdate,
)
from src.services.realtime import realtime_hub
from src.cache import invalidate_cache_tags
import uuid, datetime as dt

router = APIRouter()


@router.post('/threads', status_code=201)
async def create_thread(request: Request, payload: ThreadCreate):
    verify_jwt(request)
    p = payload.dict()
    thread_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat() + 'Z'
    record = {
        'id': thread_id,
        'title': p.get('title'),
        'thread_type': p.get('thread_type') or 'group',
        'channel_key': p.get('channel_key'),
        'context_type': p.get('context_type'),
        'context_id': p.get('context_id'),
        'created_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None,
        'created_at': now,
        'last_activity_at': now
    }
    try:
        db.table('threads').insert(record).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='DB error creating thread')

    # add participants if provided
    parts = p.get('participants') or []
    for part in parts:
        try:
            db.table('thread_participants').insert({
                'thread_id': thread_id,
                'user_id': part.get('user_id'),
                'role': part.get('role')
            }).execute()
        except Exception:
            pass

    # ensure creator membership exists
    actor = getattr(request.state, 'user', {}) if getattr(request.state, 'user', None) else {}
    creator = actor.get('sub') or actor.get('user_id')
    if creator:
        try:
            db.table('thread_participants').upsert(
                {'thread_id': thread_id, 'user_id': creator, 'role': 'owner'},
                on_conflict='thread_id,user_id',
            ).execute()
        except Exception:
            pass

    try:
        audit_event('create_thread', {'thread_id': thread_id, 'title': record.get('title')}, actor_id=(creator if creator else None), event_class='threads', action='create', subject_type='thread', subject_id=thread_id)
    except Exception:
        pass

    try:
        await realtime_hub.broadcast('chat_updates', {
            'event': 'thread_created',
            'thread_id': thread_id,
            'title': record.get('title'),
            'channel_key': record.get('channel_key'),
            'at': now,
        })
    except Exception:
        pass

    invalidate_cache_tags('staff', 'crm', 'chat_threads')

    return {'status': 'created', 'thread': record}


@router.post('/threads/channels', status_code=201)
async def create_channel(request: Request, payload: ChannelCreate):
    verify_jwt(request)
    actor = getattr(request.state, 'user', {}) if getattr(request.state, 'user', None) else {}
    creator = actor.get('sub') or actor.get('user_id')
    thread_payload = ThreadCreate(
        title=payload.title,
        thread_type='channel',
        channel_key=payload.channel_key,
        context_type=payload.context_type,
        context_id=payload.context_id,
        participants=[{'user_id': member_id, 'role': 'member'} for member_id in (payload.member_ids or [])],
    )
    return await create_thread(request, thread_payload)


@router.get('/threads')
def list_threads(request: Request):
    payload = verify_jwt(request)
    actor = payload.get('sub') or payload.get('user_id')
    roles = set(payload.get('roles') or [])

    if 'admin' in roles or 'management' in roles:
        resp = db.table('threads').select('*').order('last_activity_at', desc=True).limit(200).execute()
        data = resp.data or []
    else:
        memberships = (
            db.table('thread_participants')
            .select('thread_id')
            .eq('user_id', actor)
            .limit(500)
            .execute()
        )
        thread_ids = [row.get('thread_id') for row in (memberships.data or []) if row.get('thread_id')]
        if thread_ids:
            batch = db.table('threads').select('*').in_('id', thread_ids).execute()
            data = batch.data or []
        else:
            data = []
        data.sort(key=lambda x: x.get('last_activity_at') or '', reverse=True)

    try:
        audit_event('list_threads', {'count': len(data)}, actor_id=actor, event_class='threads')
    except Exception:
        pass
    return data


@router.get('/threads/channels')
def list_channels(request: Request):
    payload = verify_jwt(request)
    actor = payload.get('sub') or payload.get('user_id')
    roles = set(payload.get('roles') or [])

    if 'admin' in roles or 'management' in roles:
        resp = db.table('threads').select('*').eq('thread_type', 'channel').order('last_activity_at', desc=True).limit(200).execute()
        return resp.data or []

    memberships = db.table('thread_participants').select('thread_id').eq('user_id', actor).limit(500).execute()
    ids = [m.get('thread_id') for m in (memberships.data or []) if m.get('thread_id')]
    if ids:
        batch = db.table('threads').select('*').in_('id', ids).eq('thread_type', 'channel').execute()
        channels = batch.data or []
    else:
        channels = []
    channels.sort(key=lambda x: x.get('last_activity_at') or '', reverse=True)
    return channels


@router.post('/threads/{thread_id}/members', status_code=201)
async def add_member(request: Request, thread_id: str, payload: ThreadMemberCreate):
    auth = verify_jwt(request)
    roles = set(auth.get('roles') or [])
    actor = auth.get('sub') or auth.get('user_id')
    if not ('admin' in roles or 'management' in roles or 'hr' in roles or 'ops' in roles):
        raise HTTPException(status_code=403, detail='Insufficient role to add members')
    try:
        db.table('thread_participants').upsert(
            {
                'thread_id': thread_id,
                'user_id': payload.user_id,
                'role': payload.role or 'member',
            },
            on_conflict='thread_id,user_id',
        ).execute()
        await realtime_hub.broadcast('chat_updates', {
            'event': 'member_added',
            'thread_id': thread_id,
            'user_id': payload.user_id,
            'by': actor,
            'at': dt.datetime.utcnow().isoformat() + 'Z',
        })
        return {'status': 'added', 'thread_id': thread_id, 'user_id': payload.user_id}
    except Exception:
        raise HTTPException(status_code=500, detail='DB error adding member')


@router.delete('/threads/{thread_id}/members/{user_id}')
async def remove_member(request: Request, thread_id: str, user_id: str):
    auth = verify_jwt(request)
    roles = set(auth.get('roles') or [])
    actor = auth.get('sub') or auth.get('user_id')
    if not ('admin' in roles or 'management' in roles or actor == user_id):
        raise HTTPException(status_code=403, detail='Insufficient role to remove member')
    try:
        db.table('thread_participants').delete().eq('thread_id', thread_id).eq('user_id', user_id).execute()
        await realtime_hub.broadcast('chat_updates', {
            'event': 'member_removed',
            'thread_id': thread_id,
            'user_id': user_id,
            'by': actor,
            'at': dt.datetime.utcnow().isoformat() + 'Z',
        })
        return {'status': 'removed', 'thread_id': thread_id, 'user_id': user_id}
    except Exception:
        raise HTTPException(status_code=500, detail='DB error removing member')


@router.get('/threads/{thread_id}/messages')
def list_messages(request: Request, thread_id: str, limit: int = 100, offset: int = 0):
    verify_jwt(request)
    try:
        resp = (
            db.table('thread_messages')
            .select('*')
            .eq('thread_id', thread_id)
            .order('created_at', desc=False)
            .range(offset, offset + max(1, min(limit, 500)) - 1)
            .execute()
        )
        return resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='DB error listing messages')


@router.post('/threads/{thread_id}/messages', status_code=201)
async def post_message(request: Request, thread_id: str, payload: MessageCreate):
    verify_jwt(request)
    p = payload.dict()
    msg_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat() + 'Z'
    sender = getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None
    record = {
        'id': msg_id,
        'thread_id': thread_id,
        'sender': sender,
        'content': p.get('content'),
        'created_at': now,
        'metadata': p.get('metadata') or {}
    }
    try:
        db.table('thread_messages').insert(record).execute()
        db.table('threads').update({'last_activity_at': record['created_at']}).eq('id', thread_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='DB error posting message')

    try:
        actor = getattr(request.state, 'user', None)
        audit_event('post_thread_message', {'thread_id': thread_id, 'message_id': msg_id}, actor_id=(actor.get('sub') if actor else None), event_class='threads', action='message_post', subject_type='thread', subject_id=thread_id)
    except Exception:
        pass

    try:
        await realtime_hub.broadcast('chat_updates', {
            'event': 'thread_message_posted',
            'thread_id': thread_id,
            'message_id': msg_id,
            'sender': sender,
            'at': now,
            'metadata': record.get('metadata') or {},
        })
    except Exception:
        pass

    invalidate_cache_tags('staff', 'crm', 'chat_threads')

    return {'status': 'posted', 'message': record}


@router.post('/threads/{thread_id}/read')
def mark_thread_read(request: Request, thread_id: str, payload: dict):
    auth = verify_jwt(request)
    user_id = auth.get('sub') or auth.get('user_id')
    now = dt.datetime.utcnow().isoformat() + 'Z'
    marker = {
        'thread_id': thread_id,
        'user_id': user_id,
        'last_read_message_id': payload.get('last_read_message_id'),
        'last_read_at': now,
    }
    try:
        db.table('thread_reads').upsert(marker, on_conflict='thread_id,user_id').execute()
        return {'status': 'ok', 'read_marker': marker}
    except Exception:
        raise HTTPException(status_code=500, detail='DB error marking thread read')


@router.get('/threads/unread/summary')
def unread_summary(request: Request):
    auth = verify_jwt(request)
    user_id = auth.get('sub') or auth.get('user_id')

    try:
        memberships = db.table('thread_participants').select('thread_id').eq('user_id', user_id).limit(500).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='DB error reading memberships')

    summary = []
    for row in (memberships.data or []):
        thread_id = row.get('thread_id')
        if not thread_id:
            continue
        try:
            reads = db.table('thread_reads').select('last_read_at').eq('thread_id', thread_id).eq('user_id', user_id).limit(1).execute()
            last_read_at = ((reads.data or [{}])[0]).get('last_read_at')

            all_msgs = db.table('thread_messages').select('id,sender,created_at').eq('thread_id', thread_id).order('created_at', desc=False).limit(1000).execute()
            msgs = all_msgs.data or []
            unread = 0
            last_message_at = None
            for msg in msgs:
                msg_at = msg.get('created_at')
                last_message_at = msg_at or last_message_at
                if msg.get('sender') == user_id:
                    continue
                if not last_read_at or (msg_at and msg_at > last_read_at):
                    unread += 1

            summary.append({
                'thread_id': thread_id,
                'unread_count': unread,
                'last_message_at': last_message_at,
            })
        except Exception:
            continue

    summary.sort(key=lambda x: x.get('last_message_at') or '', reverse=True)
    return {'items': summary}


@router.post('/threads/{thread_id}/presence')
async def set_presence(request: Request, thread_id: str, payload: PresenceUpdate):
    auth = verify_jwt(request)
    user_id = auth.get('sub') or auth.get('user_id')
    status = (payload.status or 'online').strip().lower()
    if status not in {'online', 'away', 'offline'}:
        raise HTTPException(status_code=400, detail='Invalid presence status')
    now = dt.datetime.utcnow().isoformat() + 'Z'
    try:
        rec = {
            'thread_id': thread_id,
            'user_id': user_id,
            'status': status,
            'last_seen_at': now,
        }
        db.table('thread_presence').upsert(rec, on_conflict='thread_id,user_id').execute()
        await realtime_hub.broadcast('chat_updates', {
            'event': 'presence_updated',
            'thread_id': thread_id,
            'user_id': user_id,
            'status': status,
            'at': now,
        })
        return {'status': 'ok', 'presence': rec}
    except Exception:
        raise HTTPException(status_code=500, detail='DB error updating presence')


@router.get('/threads/{thread_id}/presence')
def list_presence(request: Request, thread_id: str):
    verify_jwt(request)
    try:
        resp = db.table('thread_presence').select('thread_id,user_id,status,last_seen_at').eq('thread_id', thread_id).order('last_seen_at', desc=True).limit(200).execute()
        return resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='DB error listing presence')

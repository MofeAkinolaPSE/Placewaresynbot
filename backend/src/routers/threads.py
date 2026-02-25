from fastapi import APIRouter, Request, HTTPException
from src.middleware import verify_jwt
from src.db import supabase, audit_event
from src.schemas.threads import ThreadCreate, MessageCreate
import uuid, datetime as dt

router = APIRouter()


@router.post('/threads', status_code=201)
async def create_thread(request: Request, payload: ThreadCreate):
    verify_jwt(request)
    p = payload.dict()
    thread_id = str(uuid.uuid4())
    record = {
        'id': thread_id,
        'title': p.get('title'),
        'created_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None,
        'created_at': dt.datetime.utcnow().isoformat() + 'Z',
        'last_activity_at': dt.datetime.utcnow().isoformat() + 'Z'
    }
    try:
        supabase.table('threads').insert(record).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='DB error creating thread')

    # add participants if provided
    parts = p.get('participants') or []
    for part in parts:
        try:
            supabase.table('thread_participants').insert({
                'thread_id': thread_id,
                'user_id': part.get('user_id'),
                'role': part.get('role')
            }).execute()
        except Exception:
            pass

    try:
        actor = getattr(request.state, 'user', None)
        audit_event('create_thread', {'thread_id': thread_id, 'title': record.get('title')}, actor_id=(actor.get('sub') if actor else None), event_class='threads', action='create', subject_type='thread', subject_id=thread_id)
    except Exception:
        pass

    return {'status': 'created', 'thread': record}


@router.get('/threads')
async def list_threads(request: Request):
    verify_jwt(request)
    resp = supabase.table('threads').select('*').order('last_activity_at', desc=True).limit(200).execute()
    data = resp.data or []
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('list_threads', {'count': len(data)}, actor_id=(actor.get('sub') if actor else None), event_class='threads')
    except Exception:
        pass
    return data


@router.post('/threads/{thread_id}/messages', status_code=201)
async def post_message(request: Request, thread_id: str, payload: MessageCreate):
    verify_jwt(request)
    p = payload.dict()
    msg_id = str(uuid.uuid4())
    record = {
        'id': msg_id,
        'thread_id': thread_id,
        'sender': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None,
        'content': p.get('content'),
        'created_at': dt.datetime.utcnow().isoformat() + 'Z',
        'metadata': p.get('metadata') or {}
    }
    try:
        supabase.table('thread_messages').insert(record).execute()
        supabase.table('threads').update({'last_activity_at': record['created_at']}).eq('id', thread_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='DB error posting message')

    try:
        actor = getattr(request.state, 'user', None)
        audit_event('post_thread_message', {'thread_id': thread_id, 'message_id': msg_id}, actor_id=(actor.get('sub') if actor else None), event_class='threads', action='message_post', subject_type='thread', subject_id=thread_id)
    except Exception:
        pass

    return {'status': 'posted', 'message': record}

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from src.middleware import verify_jwt, require_role
from src.db import db, audit_event
from src.schemas.documents import DocumentCreate, AttachRequest, ApprovalRequest
import os, uuid, hashlib
import datetime as dt
from fastapi import HTTPException
import time

# Simple in-memory upload token store for short-lived proxy uploads.
# Token -> {document_id, filename, expires_at}
from src.utils.shared_dict import SharedDict
UPLOAD_TOKENS = SharedDict("upload_token", 86400)  # shared across workers

router = APIRouter()

FILES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'documents_files')


@router.get('/documents')
def list_documents(request: Request):
    verify_jwt(request)
    try:
        resp = db.table('documents').select('*').order('created_at', desc=True).execute()
        docs = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to list documents')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('list_documents', {'count': len(docs)}, actor_id=(actor.get('sub') if actor else None), event_class='documents')
    except Exception:
        pass
    return docs


@router.post('/documents', status_code=201)
def create_document(request: Request, payload: DocumentCreate):
    verify_jwt(request, required_role='ops')
    doc = payload.dict()
    doc_record = {**doc, 'created_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None}
    try:
        resp = db.table('documents').insert(doc_record).execute()
        created = resp.data[0] if resp.data else doc_record
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to create document')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('create_document', {'document': created.get('title')}, actor_id=(actor.get('sub') if actor else None), event_class='documents', action='create', subject_type='document', subject_id=created.get('id'))
    except Exception:
        pass
    return {'status': 'created', 'document': created}


@router.post('/documents/{document_id}/upload-version')
async def upload_version(request: Request, document_id: str, file: UploadFile = File(...)):
    verify_jwt(request)
    # Reject document_id values that could escape the uploads directory
    import re as _re
    if not _re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', document_id):
        raise HTTPException(status_code=422, detail='Invalid document_id')
    # generate version id
    version_id = str(uuid.uuid4())
    filename = file.filename
    contents = await file.read()
    size = len(contents)
    checksum = hashlib.sha256(contents).hexdigest()
    subdir = os.path.join(FILES_DIR, document_id)
    # Guard against symlink/traversal attacks after joining
    resolved = os.path.realpath(subdir)
    base = os.path.realpath(FILES_DIR)
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise HTTPException(status_code=422, detail='Invalid document_id')
    os.makedirs(subdir, exist_ok=True)
    storage_name = f"{version_id}_{filename}"
    storage_path = os.path.join(subdir, storage_name)
    with open(storage_path, 'wb') as fh:
        fh.write(contents)

    version_record = {
        'id': version_id,
        'document_id': document_id,
        'version_number': 1,
        'storage_path': storage_path,
        'filename': filename,
        'content_type': file.content_type,
        'size_bytes': size,
        'uploaded_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None,
        'uploaded_at': dt.datetime.utcnow().isoformat() + 'Z',
        'checksum': checksum,
    }

    try:
        # insert metadata into DB (file bytes already written locally)
        db.table('document_versions').insert(version_record).execute()
        db.table('documents').update({'current_version': version_id}).eq('id', document_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to store document version')

    try:
        actor = getattr(request.state, 'user', None)
        audit_event('upload_document_version', {'document_id': document_id, 'version_id': version_id, 'filename': filename}, actor_id=(actor.get('sub') if actor else None), event_class='documents', action='upload', subject_type='document', subject_id=document_id)
    except Exception:
        pass

    return {'status': 'uploaded', 'version': version_record}


@router.post('/documents/{document_id}/generate-upload')
def generate_upload(request: Request, document_id: str, payload: dict):
    """Generate a short-lived proxy upload URL (server will accept the upload and push to Supabase Storage).

    This is a lightweight alternative to direct Supabase-signed URLs for environments
    where the Supabase client may not support presigned upload links. Returns a tokenized
    upload URL valid for `expires_in` seconds (default 300).
    """
    verify_jwt(request)
    filename = payload.get('filename')
    expires_in = int(payload.get('expires_in', 300))
    token = str(uuid.uuid4())
    UPLOAD_TOKENS[token] = {'document_id': document_id, 'filename': filename, 'expires_at': time.time() + expires_in}
    upload_url = f"/documents/uploads/{token}"
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('generate_document_upload', {'document_id': document_id, 'filename': filename}, actor_id=(actor.get('sub') if actor else None), event_class='documents', action='generate_upload', subject_type='document', subject_id=document_id)
    except Exception:
        pass
    return {'upload_url': upload_url, 'expires_in': expires_in, 'token': token}


@router.put('/documents/uploads/{token}')
async def proxy_upload(request: Request, token: str, file: UploadFile = File(...)):
    """Accepts a file upload using a short-lived token and stores the object in Supabase Storage,
    then creates a document_version metadata record and updates the document's current_version.
    """
    verify_jwt(request)
    meta = UPLOAD_TOKENS.get(token)
    if not meta or meta.get('expires_at', 0) < time.time():
        raise HTTPException(status_code=410, detail='Upload token expired or invalid')
    document_id = meta.get('document_id')
    filename = meta.get('filename') or file.filename
    contents = await file.read()
    size = len(contents)
    checksum = hashlib.sha256(contents).hexdigest()
    version_id = str(uuid.uuid4())
    storage_path = f"{document_id}/{version_id}_{filename}"
    bucket = os.getenv('SUPABASE_STORAGE_BUCKET', 'documents')
    # attempt upload to Supabase Storage
    try:
        # db.storage.from_(bucket).upload expects a file path or bytes-like object
        db.storage.from_(bucket).upload(storage_path, contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to upload to storage: {e}')

    version_record = {
        'id': version_id,
        'document_id': document_id,
        'version_number': 1,
        'storage_path': storage_path,
        'filename': filename,
        'content_type': file.content_type,
        'size_bytes': size,
        'uploaded_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None,
        'uploaded_at': dt.datetime.utcnow().isoformat() + 'Z',
        'checksum': checksum,
    }
    try:
        db.table('document_versions').insert(version_record).execute()
        db.table('documents').update({'current_version': version_id}).eq('id', document_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to store document version metadata: {e}')

    # clean up token
    try:
        del UPLOAD_TOKENS[token]
    except Exception:
        pass

    try:
        actor = getattr(request.state, 'user', None)
        audit_event('upload_document_version_via_proxy', {'document_id': document_id, 'version_id': version_id, 'filename': filename}, actor_id=(actor.get('sub') if actor else None), event_class='documents', action='upload', subject_type='document', subject_id=document_id)
    except Exception:
        pass

    return {'status': 'uploaded', 'version': version_record}


@router.post('/documents/{document_id}/attach')
def attach_document(request: Request, document_id: str, payload: AttachRequest):
    verify_jwt(request)
    attach = payload.dict()
    attach_record = {**attach, 'document_id': document_id, 'attached_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None, 'attached_at': dt.datetime.utcnow().isoformat() + 'Z'}
    try:
        db.table('document_attachments').insert(attach_record).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to attach document')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('attach_document', {'document_id': document_id, 'attached_to_table': attach.get('attached_to_table')}, actor_id=(actor.get('sub') if actor else None), event_class='documents', action='attach', subject_type='document', subject_id=document_id)
    except Exception:
        pass
    return {'status': 'attached', 'attach': attach_record}


@router.post('/documents/{document_id}/approve')
def approve_document(request: Request, document_id: str, payload: ApprovalRequest):
    verify_jwt(request, required_role='admin')
    req = payload.dict()
    now = dt.datetime.utcnow().isoformat() + 'Z'
    update = {'approval_status': req.get('approval_status'), 'approved_by': getattr(request.state, 'user', {}).get('sub') if getattr(request.state, 'user', None) else None, 'approved_at': now}
    try:
        db.table('documents').update(update).eq('id', document_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to update document approval')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('approve_document', {'document_id': document_id, 'status': req.get('approval_status')}, actor_id=(actor.get('sub') if actor else None), event_class='documents', action='approve', subject_type='document', subject_id=document_id)
    except Exception:
        pass
    return {'status': 'updated', 'document_id': document_id, 'approval_status': req.get('approval_status')}

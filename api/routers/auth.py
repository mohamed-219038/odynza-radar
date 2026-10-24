"""Sign in / out, sign-up, forgotten passwords, the signed-in user, own password, and admin user management."""
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.security import (PENDING, signup_mode, AuthSession, AuthUser, ROLES, burn_password_check, clean_username, client_ip, current_user,
                          direct_loopback, end_session, hash_password, limiter, lookup_session, password_problem,
                          require_admin, require_user, start_session, token_hash, too_many, verify_password)
from api.watch.brief import email_settings
from db.database import PasswordReset, User, get_db

router = APIRouter()

LOGIN_WINDOW = 15 * 60


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class NewUser(Credentials):
    role: str = 'member'


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserUpdate(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, max_length=256)


def user_out(u: User):
    return {'id': u.id, 'username': u.username, 'role': u.role, 'disabled': bool(u.disabled),
            'created_at': u.created_at, 'last_login_at': u.last_login_at}


@router.get('/status')
def status(request: Request, db: Session = Depends(get_db)):
    """Public: whether this browser is signed in, and whether the first admin still has to be created."""
    user = lookup_session(db, request)
    if user:
        return {'authenticated': True, 'user': user.public(), 'csrf': user.csrf}
    first = db.query(User.id).first() is None
    return {'authenticated': False, 'setup_required': first, 'setup_allowed': first and direct_loopback(request),
            'signup': 'off' if first else signup_mode()}


@router.post('/login')
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    name = body.username.strip().lower()
    for key, limit in ((f'login-ip:{ip}', 30), (f'login-fail:{name}', 8), (f'login-fail-ip:{ip}', 15)):
        wait = limiter.check(key, limit, LOGIN_WINDOW, record=key.startswith('login-ip'))
        if wait:
            logger.warning(f'[auth] sign-in throttled for {name!r} from {ip}')
            too_many(wait, 'sign-in attempts')
    user = db.query(User).filter(User.username == name).first()
    if user is None:
        burn_password_check(body.password)
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        limiter.add(f'login-fail:{name}')
        limiter.add(f'login-fail-ip:{ip}')
        logger.warning(f'[auth] failed sign-in for {name!r} from {ip}')
        raise HTTPException(401, 'Wrong username or password.')
    limiter.clear(f'login-fail:{name}')
    if user.role == PENDING:
        raise HTTPException(403, 'Your account is waiting for an admin to approve it. Try again after they do.')
    row = start_session(db, user, request, response)
    logger.info(f'[auth] {user.username} signed in from {ip}')
    return {'authenticated': True, 'user': {'id': user.id, 'username': user.username, 'role': user.role}, 'csrf': row.csrf}


@router.post('/signup', status_code=201)
def signup(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    """Self sign-up. By default the account waits for an admin's approval (SIGNUP_MODE=approval)."""
    mode = signup_mode()
    if mode == 'off' or db.query(User.id).first() is None:
        raise HTTPException(403, 'Sign-up is turned off. Ask an admin to create your account.')
    ip = client_ip(request)
    wait = limiter.check(f'signup-ip:{ip}', 5, 3600)
    if wait:
        too_many(wait, 'sign-ups from this address')
    name = clean_username(body.username)
    problem = password_problem(body.password, name)
    if problem:
        raise HTTPException(422, problem)
    if db.query(User.id).filter(User.username == name).first():
        raise HTTPException(409, 'That username is taken. Choose another one.')
    user = User(username=name, password_hash=hash_password(body.password), role='viewer' if mode == 'viewer' else PENDING)
    db.add(user)
    db.commit()
    logger.info(f'[auth] {name} signed up from {ip} ({user.role})')
    if user.role == PENDING:
        return {'authenticated': False, 'pending': True}
    row = start_session(db, user, request, response)
    return {'authenticated': True, 'user': {'id': user.id, 'username': user.username, 'role': user.role}, 'csrf': row.csrf}


class ForgotIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=1, max_length=256)


RESET_FOR = timedelta(minutes=30)
FORGOT_SENT = ('If that account exists and its username is an email address, a reset link is on its way. '
               'It works for 30 minutes. No email? Ask an admin to reset your password on the Team page.')


def send_reset_email(to: str, link: str):
    """Runs after the response, so the answer and its timing never show whether the account exists."""
    s = email_settings()
    msg = EmailMessage()
    msg['Subject'] = 'Reset your Odynza Radar password'
    msg['From'] = s['sender']
    msg['To'] = to
    msg.set_content(f'Someone asked to reset the Odynza Radar password for {to}.\n\n'
                    f'Open this link within 30 minutes to choose a new password:\n{link}\n\n'
                    'If it was not you, ignore this email; your password stays the same.')
    try:
        with smtplib.SMTP(s['host'], s['port'], timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(s['user'], s['password'])
            smtp.send_message(msg)
        logger.info(f'[auth] password reset link sent to {to}')
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(f'[auth] password reset email to {to} failed: {type(exc).__name__}')


@router.post('/forgot')
def forgot(body: ForgotIn, request: Request, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Public: emails a one-time reset link when the username is an email address. The answer is the same either way."""
    s = email_settings()
    if not s['user'] or not s['password']:
        raise HTTPException(503, 'Email is not set up on this server, so reset links cannot be sent. '
                                 'Ask an admin to reset your password on the Team page.')
    ip = client_ip(request)
    name = body.username.strip().lower()
    for key, limit in ((f'forgot-ip:{ip}', 10), (f'forgot-name:{name}', 3)):
        wait = limiter.check(key, limit, 3600)
        if wait:
            too_many(wait, 'reset requests')
    user = db.query(User).filter(User.username == name).first()
    if user and not user.disabled and user.role != PENDING and '@' in name:
        db.query(PasswordReset).filter(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)).delete()
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(token_hash=token_hash(token), user_id=user.id, expires_at=datetime.utcnow() + RESET_FOR))
        db.commit()
        base = (os.getenv('RADAR_PUBLIC_URL') or '').strip().rstrip('/') or str(request.base_url).rstrip('/')
        tasks.add_task(send_reset_email, user.username, f'{base}/reset?token={token}')
    else:
        logger.info(f'[auth] reset asked for {name!r}: no email to send to')
    return {'message': FORGOT_SENT}


@router.post('/reset')
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    """Public: sets a new password with a link from /forgot. The link works once, and every browser is signed out."""
    wait = limiter.check(f'reset-ip:{client_ip(request)}', 20, 3600)
    if wait:
        too_many(wait, 'reset attempts')
    row = db.get(PasswordReset, token_hash(body.token))
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        raise HTTPException(400, 'This reset link is used up or has expired. Ask for a new one.')
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        raise HTTPException(400, 'This reset link is used up or has expired. Ask for a new one.')
    problem = password_problem(body.password, user.username)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = hash_password(body.password)
    row.used_at = datetime.utcnow()
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.commit()
    limiter.clear(f'login-fail:{user.username}')
    logger.info(f'[auth] {user.username} chose a new password with a reset link')
    return {'message': 'Your new password is saved. Sign in with it now.'}


@router.post('/setup')
def first_admin(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    """Create the first admin from a browser on this computer only, and only while no account exists."""
    if db.query(User.id).first() is not None:
        raise HTTPException(409, 'An account already exists. Sign in instead.')
    if not direct_loopback(request):
        raise HTTPException(403, 'Create the first admin on the server computer itself (open http://localhost:8000), '
                                 'or run: python scripts/create_user.py <username> --admin')
    name = clean_username(body.username)
    problem = password_problem(body.password, name)
    if problem:
        raise HTTPException(422, problem)
    user = User(username=name, password_hash=hash_password(body.password), role='admin')
    db.add(user)
    db.commit()
    row = start_session(db, user, request, response)
    logger.info(f'[auth] first admin {name} created')
    return {'authenticated': True, 'user': {'id': user.id, 'username': user.username, 'role': user.role}, 'csrf': row.csrf}


@router.post('/logout')
def logout(request: Request, response: Response, user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    end_session(db, request, response)
    return {'authenticated': False}


@router.get('/me')
def me(user: AuthUser = Depends(current_user)):
    return {'user': user.public(), 'csrf': user.csrf}


@router.post('/password')
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: AuthUser = Depends(require_user), db: Session = Depends(get_db)):
    wait = limiter.check(f'password:{user.id}', 10, LOGIN_WINDOW)
    if wait:
        too_many(wait, 'attempts')
    row = db.get(User, user.id)
    if not verify_password(body.current_password, row.password_hash):
        raise HTTPException(403, 'Your current password is not correct.')
    problem = password_problem(body.new_password, row.username)
    if problem:
        raise HTTPException(422, problem)
    row.password_hash = hash_password(body.new_password)
    # Every other signed-in browser of this user is signed out.
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.commit()
    session = start_session(db, row, request, response)
    return {'changed': True, 'csrf': session.csrf}


# ---- Admin ------------------------------------------------------------------------------

@router.get('/users')
def list_users(admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.query(User).order_by(User.username).all()]


@router.post('/users', status_code=201)
def create_user(body: NewUser, admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    name = clean_username(body.username)
    if body.role not in ROLES:
        raise HTTPException(422, 'Role must be admin, member, viewer or client.')
    problem = password_problem(body.password, name)
    if problem:
        raise HTTPException(422, problem)
    if db.query(User.id).filter(User.username == name).first():
        raise HTTPException(409, 'That username is taken.')
    user = User(username=name, password_hash=hash_password(body.password), role=body.role, created_at=datetime.utcnow())
    db.add(user)
    db.commit()
    logger.info(f'[auth] {admin.username} created user {name} ({body.role})')
    return user_out(user)


def other_admins(db, user_id):
    return db.query(User).filter(User.role == 'admin', User.disabled.is_(False), User.id != user_id).count()


@router.patch('/users/{user_id}')
def update_user(user_id: int, body: UserUpdate, admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, 'User not found')
    losing_admin = user.role == 'admin' and ((body.role is not None and body.role != 'admin') or body.disabled)
    if losing_admin and not other_admins(db, user.id):
        raise HTTPException(409, 'Keep at least one active admin.')
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, 'Role must be admin, member, viewer or client.')
        user.role = body.role
    if body.disabled is not None:
        user.disabled = body.disabled
    if body.password:
        problem = password_problem(body.password, user.username)
        if problem:
            raise HTTPException(422, problem)
        user.password_hash = hash_password(body.password)
    if body.disabled or body.password or body.role is not None:
        db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.commit()
    logger.info(f'[auth] {admin.username} updated user {user.username}')
    return user_out(user)


@router.delete('/users/{user_id}')
def delete_user(user_id: int, admin: AuthUser = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, 'User not found')
    if user.id == admin.id:
        raise HTTPException(409, 'You cannot delete your own account.')
    if user.role == 'admin' and not other_admins(db, user.id):
        raise HTTPException(409, 'Keep at least one active admin.')
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.delete(user)
    db.commit()
    logger.info(f'[auth] {admin.username} deleted user {user.username}')
    return {'deleted': user_id}

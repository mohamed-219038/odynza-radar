"""M1 Strategy plans: the n8n strategy agents write each plan and post it back here.

Radar builds the request (see api/routers/radar_plans.py), starts the n8n webhook and stores the
validated plan that n8n posts back. No model calls are made from this router.
"""
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from api.security import direct_loopback, require_user
from db.database import StrategyPlan, get_db

router = APIRouter()

STALE_AFTER = timedelta(minutes=20)


class PlanResult(BaseModel):
    plan: dict
    model: str = Field(default='', max_length=100)


class PlanFailure(BaseModel):
    error: str = Field(min_length=1, max_length=2000)


def callback_allowed(request: Request, token: str | None):
    """With N8N_SHARED_TOKEN set, n8n must send it. Without it, only a direct call from this computer is accepted
    (not one relayed by a reverse proxy, which would make every visitor look local)."""
    import hmac
    expected = os.getenv('N8N_SHARED_TOKEN', '').strip()
    if expected:
        if not token or not hmac.compare_digest(token.encode('utf-8'), expected.encode('utf-8')):
            raise HTTPException(401, 'Invalid or missing X-Radar-Token.')
        return
    if not direct_loopback(request):
        raise HTTPException(403, 'Set N8N_SHARED_TOKEN to accept plans from n8n on another machine.')

def serialize(plan: StrategyPlan, full=False):
    out = {'plan_id': plan.id, 'session_id': plan.session_id, 'company_id': plan.company_id,
           'company_name': plan.company_name, 'status': plan.status, 'error': plan.error,
           'created_at': plan.created_at, 'updated_at': plan.updated_at,
           'objective': (plan.inputs or {}).get('objective', ''),
           'period': {'start_date': (plan.inputs or {}).get('start_date'), 'end_date': (plan.inputs or {}).get('end_date')}}
    if full:
        out.update({'inputs': plan.inputs, 'plan': plan.plan, 'validation_errors': plan.validation_errors or []})
    return out


def expire_stale(db, rows):
    now = datetime.utcnow()
    changed = False
    for row in rows:
        if row.status in ('queued', 'running') and row.updated_at and now - row.updated_at > STALE_AFTER:
            row.status, row.error = 'failed', 'n8n did not send a result. Open the latest n8n execution to see which node stopped.'
            changed = True
    if changed:
        db.commit()


def get_plan(db, plan_id):
    plan = db.get(StrategyPlan, plan_id)
    if plan is None:
        raise HTTPException(404, 'Strategy plan not found')
    return plan


# ---- Endpoints --------------------------------------------------------------------------


@router.get('/plans/{plan_id}', dependencies=[Depends(require_user)])
def read_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    expire_stale(db, [plan])
    return serialize(plan, full=True)


@router.delete('/plans/{plan_id}', dependencies=[Depends(require_user)])
def delete_plan(plan_id: str, db: Session = Depends(get_db)):
    from db.database import StrategyResult
    db.query(StrategyResult).filter_by(plan_id=plan_id).delete()
    db.delete(get_plan(db, plan_id))
    db.commit()
    return {'deleted': plan_id}


@router.post('/plans/{plan_id}/result')
def save_result(plan_id: str, body: PlanResult, request: Request, db: Session = Depends(get_db),
                x_radar_token: str | None = Header(default=None)):
    callback_allowed(request, x_radar_token)
    return save_radar_result(get_plan(db, plan_id), body, db)


def save_radar_result(plan: StrategyPlan, body: PlanResult, db: Session):
    """Radar plans are fixed where they can be (dates, shares, events) and fail only when a core part is missing."""
    from api.strategy_plan import PlanProblem, clean
    try:
        saved, notes = clean(body.plan, plan.inputs)
    except (PlanProblem, ValidationError, ValueError) as exc:
        errors = ([str(exc)] if not isinstance(exc, ValidationError) else
                  ['.'.join(map(str, e['loc'])) + ': ' + e['msg'] for e in exc.errors(include_input=False)[:8]])
        plan.status, plan.validation_errors = 'failed', errors
        plan.error = 'The plan from n8n failed Radar validation.'
        db.commit()
        raise HTTPException(422, {'errors': errors}) from None
    saved['model'], saved['notes'] = body.model, notes
    plan.plan, plan.status, plan.error, plan.validation_errors = saved, 'completed', None, []
    db.commit()
    return serialize(plan)


@router.post('/plans/{plan_id}/fail')
def save_failure(plan_id: str, body: PlanFailure, request: Request, db: Session = Depends(get_db),
                 x_radar_token: str | None = Header(default=None)):
    callback_allowed(request, x_radar_token)
    plan = get_plan(db, plan_id)
    if plan.status != 'completed':
        plan.status, plan.error = 'failed', body.error
        db.commit()
    return serialize(plan)

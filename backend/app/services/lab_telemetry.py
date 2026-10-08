"""Capture all assigned users' cafeteria requests, including failures and capped views."""
import contextvars
import json
import time
import uuid
from fastapi.routing import APIRoute
from app.database import get_pool

_current_id = contextvars.ContextVar('lab_request_id',default=None)


def request_id():
    return _current_id.get() or str(uuid.uuid4())


class ExperimentRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            rid = str(uuid.uuid4())
            token = _current_id.set(rid)
            received = time.monotonic()
            failed = False
            try:
                if request.method=='POST':
                    try:
                        body = await request.json()
                        user = ((body or {}).get('userRequest',{}).get('user') or {}).get('id')
                        if user:
                            await get_pool().execute('''INSERT INTO lab_requests(request_id,experiment_id,user_id,variant,route)
                               SELECT $1,a.experiment_id,a.user_id,a.variant,$3 FROM lab_assignments a
                               JOIN lab_experiments e ON e.id=a.experiment_id
                               WHERE a.user_id=$2 AND e.status IN ('running','paused','observing')
                               AND a.assigned_at+INTERVAL '168 hours'>NOW() ON CONFLICT DO NOTHING''',rid,user,request.url.path)
                    except (RuntimeError,json.JSONDecodeError,AttributeError,TypeError):
                        pass
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception("failed to capture experiment request")
                response = await original(request)
                failed = response.status_code >= 400
                return response
            except Exception:
                failed = True
                raise
            finally:
                try:
                    await get_pool().execute('''UPDATE lab_requests SET completed_at=NOW(),latency_ms=$2,
                       error=COALESCE(error,FALSE) OR $3,
                       response_included=COALESCE(response_included,FALSE),
                       error_code=CASE WHEN $3 THEN 'request_failed' ELSE error_code END WHERE request_id=$1''',
                       rid,(time.monotonic()-received)*1000,failed)
                    from app.services import experiment_lab
                    await experiment_lab.check_operational_alarm(rid)
                except RuntimeError:
                    pass
                except Exception:
                    # Telemetry failure must not replace the meal response; incomplete rows block quality.
                    import logging
                    logging.getLogger(__name__).exception('failed to finalize experiment request')
                _current_id.reset(token)
        return handler

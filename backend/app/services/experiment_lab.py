"""Protocol lifecycle and ITT analysis, isolated from legacy button experiments."""
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.database import get_pool
from app.schemas.experiment_lab import Protocol
from app.services import lab_stats

UTC = timezone.utc
ACTIVE = ('running','paused','observing')


def decode(row):
    item = dict(row)
    for key in ('protocol','result','details'):
        if isinstance(item.get(key),str):
            item[key] = json.loads(item[key])
    return item


def policy_checksum():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ('promotion_preview.py','recommendation_policy.py','promotion_cards.py','promotions.py',
                 'recommendations.py','lab_delivery.py'):
        digest.update(name.encode())
        digest.update((root/name).read_bytes())
    return digest.hexdigest()


def canonical_hash(protocol):
    return hashlib.sha256(json.dumps(protocol,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def choose_variant(key, salt, user_id):
    digest = hashlib.sha256(f'{key}:{salt}:{user_id}'.encode()).digest()
    return 'A' if int.from_bytes(digest[:8],'big') < 2**63 else 'B'


def is_qa(user_id):
    excluded = {v.strip() for v in os.getenv('EXPERIMENT_QA_IDS','').split(',') if v.strip()}
    developer = os.getenv('DEVELOPER_ID','').strip()
    if developer:
        excluded.add(developer)
    return not user_id or user_id in excluded


async def audit(conn, experiment_id, actor, action, reason, details=None):
    await conn.execute('''INSERT INTO lab_audit(experiment_id,actor,action,reason,details)
                          VALUES($1,$2,$3,$4,$5::jsonb)''',
                       experiment_id,actor,action,reason,json.dumps(details or {},default=str))


async def create(payload, actor):
    protocol = payload.protocol.model_dump(mode='json')
    protocol['policy_checksum'] = policy_checksum()
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            eid = await conn.fetchval('''INSERT INTO lab_experiments
                (experiment_key,name,hypothesis,kind,protocol,config_hash,salt,created_by)
                VALUES($1,$2,$3,$4,$5::jsonb,$6,$7,$8) RETURNING id''',
                'student-bundle-'+secrets.token_hex(8), payload.name,payload.hypothesis,payload.kind,
                json.dumps(protocol),canonical_hash(protocol),secrets.token_hex(32),actor)
            await audit(conn,eid,actor,'create','설계 초안 저장')
    return eid


async def list_designs():
    async with get_pool().acquire() as conn:
        rows = await conn.fetch('''SELECT e.id,e.experiment_key,e.name,e.hypothesis,e.kind,e.protocol,
           e.config_hash,e.status,e.started_at,e.enrollment_closed_at,e.stopped_at,e.created_at,
           (SELECT COUNT(*) FROM lab_assignments a WHERE a.experiment_id=e.id) AS assigned_users,
           (SELECT result FROM lab_analysis_runs r WHERE r.experiment_id=e.id ORDER BY id DESC LIMIT 1) AS result
           FROM lab_experiments e ORDER BY id DESC''')
    return [decode(r) for r in rows]


async def get_design(eid, conn=None):
    if conn is None:
        async with get_pool().acquire() as own:
            return await get_design(eid,own)
    row = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1',eid)
    if not row:
        raise ValueError('실험을 찾을 수 없습니다.')
    item = decode(row)
    item.pop('salt',None)
    item.pop('created_by',None)
    return item


async def update_draft(eid, payload, actor):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1 FOR UPDATE',eid)
            if not row or row['status'] != 'draft':
                raise ValueError('시작 후에는 계획을 수정할 수 없습니다. 새 실험을 만드세요.')
            protocol = payload.protocol.model_dump(mode='json')
            protocol['policy_checksum'] = policy_checksum()
            await conn.execute('''UPDATE lab_experiments SET name=$2,hypothesis=$3,kind=$4,
                    protocol=$5::jsonb,config_hash=$6 WHERE id=$1''',
                    eid,payload.name,payload.hypothesis,payload.kind,json.dumps(protocol),canonical_hash(protocol))
            await audit(conn,eid,actor,'update','계획 검토',{'before_hash':row['config_hash'],'after_hash':canonical_hash(protocol)})


async def start_blockers(design,conn):
    p = design['protocol']
    missing = []
    if p.get('policy_checksum') != policy_checksum():
        missing.append('정책 코드 checksum 변경: 새 계획으로 재검토')
    for field,label in [('p95_limit_ms','p95 지연 한계'),('minimum_bundle_completion','B 3개 확보율 한계'),
                        ('readiness_notes','계측·클릭 필터 검증 기록'),('device_qa_notes','실기기 QA 기록')]:
        if not p.get(field):
            missing.append(label)
    if design['kind']=='ab':
        for field,label in [('baseline_rate','최신 기준율'),('baseline_as_of','기준율 기준 시각'),
                            ('baseline_source','기준율·분산·θ·모집 가능성 검토 근거')]:
            if not p.get(field):
                missing.append(label)
        if p.get('baseline_as_of'):
            age = datetime.now(UTC)-datetime.fromisoformat(p['baseline_as_of'])
            if age < timedelta(0) or age > timedelta(days=14):
                missing.append('최근 14일 안의 기준율 재검증')
        aa_id = p.get('aa_experiment_id')
        aa = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1',aa_id) if aa_id else None
        run = await conn.fetchrow('SELECT * FROM lab_analysis_runs WHERE experiment_id=$1 ORDER BY id DESC LIMIT 1',aa_id) if aa else None
        if not aa or aa['kind']!='aa' or aa['status'] not in ('ready','decided') or not run:
            missing.append('완료된 별도 A/A 실험 및 분석')
        elif not (decode(run)['result'].get('quality_passed') and aa['started_at'] and
                  aa['enrollment_closed_at']-aa['started_at'] >= timedelta(days=7)):
            missing.append('7일 A/A 진단 통과')
        simulation = await conn.fetchval('''SELECT details FROM lab_audit
             WHERE experiment_id=$1 AND action='simulation' ORDER BY id DESC LIMIT 1''',design['id'])
        if not simulation or decode({'details':simulation})['details'].get('config_hash') != design['config_hash']:
            missing.append('현재 계획 hash의 검정력 시뮬레이션')
    return missing


async def enrollment(eid, action, reason, actor):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(846201)')
            raw = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1 FOR UPDATE',eid)
            if not raw:
                raise ValueError('실험을 찾을 수 없습니다.')
            d = decode(raw)
            expected = {'start':('draft',),'pause':('running',),'resume':('paused',),'close':('running','paused')}
            if d['status'] not in expected[action]:
                raise ValueError('현재 상태에서 허용하지 않는 전환입니다.')
            if action=='start':
                blockers = await start_blockers(d,conn)
                if blockers:
                    raise ValueError('시작 게이트: '+', '.join(blockers))
                other = await conn.fetchval("SELECT id FROM lab_experiments WHERE status IN ('running','paused','observing') AND id<>$1",eid)
                if other:
                    raise ValueError('동일 학식 슬롯에서 다른 실험이 진행 중입니다.')
            horizon = d['protocol'].get('aa_enrollment_days',7) if d['kind']=='aa' else 28
            if action=='resume' and datetime.now(UTC) >= d['started_at']+timedelta(days=horizon):
                raise ValueError('모집 상한이 끝났습니다. 모집을 마감하세요.')
            status = {'start':'running','pause':'paused','resume':'running','close':'observing'}[action]
            await conn.execute('''UPDATE lab_experiments SET status=$2,
                started_at=CASE WHEN $3='start' THEN NOW() ELSE started_at END,
                enrollment_closed_at=CASE WHEN $3='close' THEN NOW() ELSE enrollment_closed_at END WHERE id=$1''',eid,status,action)
            await audit(conn,eid,actor,action,reason,{'before':d['status'],'after':status})


async def stop(eid, reason, actor):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            d = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1 FOR UPDATE',eid)
            if not d or d['status'] not in ACTIVE:
                raise ValueError('운영 중인 실험만 긴급 중단할 수 있습니다.')
            count = await conn.fetchval('SELECT COUNT(*) FROM lab_assignments WHERE experiment_id=$1',eid)
            await conn.execute("UPDATE lab_experiments SET status='stopped',stopped_at=NOW(),enrollment_closed_at=COALESCE(enrollment_closed_at,NOW()) WHERE id=$1",eid)
            await audit(conn,eid,actor,'stop',reason,{'affected_assignments':count})


async def assign(user_id, place, request_id, route):
    """Called only after A is valid and its output demonstrably fits; before B selection."""
    if is_qa(user_id):
        return None
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            d = await conn.fetchrow("SELECT * FROM lab_experiments WHERE status IN ('running','paused','observing') FOR UPDATE")
            if not d:
                return None
            d = decode(d)
            now = await conn.fetchval('SELECT clock_timestamp()')
            existing = await conn.fetchrow('SELECT * FROM lab_assignments WHERE experiment_id=$1 AND user_id=$2',d['id'],user_id)
            p = d['protocol']
            total = await conn.fetchval('SELECT COUNT(*) FROM lab_assignments WHERE experiment_id=$1',d['id'])
            horizon = p.get('aa_enrollment_days',7) if d['kind']=='aa' else 28
            target_reached = d['kind']=='ab' and total >= p['total_users']
            if d['status'] in ('running','paused') and (target_reached or now >= d['started_at']+timedelta(days=horizon)):
                await conn.execute("UPDATE lab_experiments SET status='observing',enrollment_closed_at=NOW() WHERE id=$1",d['id'])
                await audit(conn,d['id'],'system','close','고정 모집 목표 또는 기간 상한 도달')
                d['status']='observing'
            if existing:
                if now >= existing['assigned_at']+timedelta(hours=168):
                    return None
                variant = existing['variant']
            else:
                if d['status'] != 'running':
                    return None
                # Daily cap check under the same lock namespace as legacy exposures.
                await conn.fetchval('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'promotion-daily-cap:{user_id}:menu_inline_card')
                capped = await conn.fetchval('''SELECT EXISTS(SELECT 1 FROM user_events WHERE user_id=$1
                     AND surface='menu_inline_card' AND event_name='promotion_exposure'
                     AND created_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')''',user_id)
                if capped:
                    return None
                variant = choose_variant(d['experiment_key'],d['salt'],user_id)
                pre = await conn.fetchval('''SELECT COUNT(DISTINCT (created_at AT TIME ZONE 'Asia/Seoul')::date)
                    FROM user_events WHERE user_id=$1 AND event_name='menu_view'
                    AND created_at >= $2::timestamptz-INTERVAL '14 days' AND created_at < $2''',user_id,now)
                await conn.execute('''INSERT INTO lab_assignments(experiment_id,user_id,variant,assigned_at,
                      pre_activity_days,first_place,eligibility_version) VALUES($1,$2,$3,$4,$5,$6,$7)''',
                      d['id'],user_id,variant,now,pre,place,p['eligibility_version'])
                if d['kind']=='ab' and total+1 >= p['total_users']:
                    await conn.execute("UPDATE lab_experiments SET status='observing',enrollment_closed_at=NOW() WHERE id=$1",d['id'])
                    await audit(conn,d['id'],'system','close','표본 목표 도달')
            await conn.execute('''INSERT INTO lab_requests(request_id,experiment_id,user_id,variant,route)
                      VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING''',request_id,d['id'],user_id,variant,route)
            return {'experiment_id':d['id'],'variant':variant,'kind':d['kind'],
                    'config_hash':d['config_hash'],'request_id':request_id,'policy_version':p['policy_version'],
                    'policy_checksum':p.get('policy_checksum')}


async def latest(eid):
    async with get_pool().acquire() as conn:
        design = await get_design(eid,conn)
        run = await conn.fetchrow('SELECT * FROM lab_analysis_runs WHERE experiment_id=$1 ORDER BY id DESC LIMIT 1',eid)
        history = await conn.fetch('SELECT action,reason,details,created_at FROM lab_audit WHERE experiment_id=$1 ORDER BY id DESC LIMIT 50',eid)
        counts = await conn.fetch('SELECT variant,COUNT(*)::int AS n FROM lab_assignments WHERE experiment_id=$1 GROUP BY variant',eid)
        return {'experiment':design,'live_assigned':{r['variant']:r['n'] for r in counts},'run':decode(run) if run else None,'history':[decode(r) for r in history],
                'start_blockers':await start_blockers(design,conn) if design['status']=='draft' else []}


COHORT_SQL = '''SELECT a.variant,a.assigned_at,a.pre_activity_days,
  EXISTS(SELECT 1 FROM user_events e WHERE e.user_id=a.user_id AND e.event_name='commerce_card_click'
    AND e.created_at>=a.assigned_at AND e.created_at<a.assigned_at+INTERVAL '168 hours'
    AND e.created_at<=$2 AND COALESCE(e.properties->>'is_preview','false')!='true') AS clicked,
  (SELECT COUNT(DISTINCT (e.created_at AT TIME ZONE 'Asia/Seoul')::date) FROM user_events e
    WHERE e.user_id=a.user_id AND e.event_name='menu_view' AND e.created_at>=a.assigned_at
    AND e.created_at<a.assigned_at+INTERVAL '168 hours' AND e.created_at<=$2
    AND COALESCE(e.properties->>'is_preview','false')!='true')::int AS activity_days
  FROM lab_assignments a WHERE a.experiment_id=$1
  AND a.assigned_at+INTERVAL '168 hours'<=$2 ORDER BY a.assigned_at'''


async def run_analysis(eid, payload, actor):
    if payload.watermark > datetime.now(UTC):
        raise ValueError('미래 watermark는 사용할 수 없습니다.')
    async with get_pool().acquire() as conn:
        async with conn.transaction(isolation='repeatable_read'):
            d = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1 FOR UPDATE',eid)
            if not d:
                raise ValueError('실험을 찾을 수 없습니다.')
            d = decode(d)
            existing = await conn.fetchrow('SELECT * FROM lab_analysis_runs WHERE experiment_id=$1 AND idempotency_key=$2',eid,payload.idempotency_key)
            if existing:
                return decode(existing)
            p = d['protocol']
            horizon = p.get('aa_enrollment_days',7) if d['kind']=='aa' else 28
            if d['status'] in ('running','paused') and datetime.now(UTC)>=d['started_at']+timedelta(days=horizon):
                await conn.execute("UPDATE lab_experiments SET status='observing',enrollment_closed_at=$2 WHERE id=$1",eid,d['started_at']+timedelta(days=horizon))
                d['status']='observing'
                d['enrollment_closed_at']=d['started_at']+timedelta(days=horizon)
                await audit(conn,eid,'system','close','고정 모집 기간 상한 도달')
            counts = await conn.fetch('SELECT variant,COUNT(*)::int AS n FROM lab_assignments WHERE experiment_id=$1 GROUP BY variant',eid)
            assigned = {v:0 for v in ('A','B')}
            assigned.update({r['variant']:r['n'] for r in counts})
            rows = [dict(r) for r in await conn.fetch(COHORT_SQL,eid,payload.watermark)]
            mature = {v:sum(r['variant']==v for r in rows) for v in ('A','B')}
            clicks = {v:sum(r['variant']==v and r['clicked'] for r in rows) for v in ('A','B')}
            effect = lab_stats.click_effect(clicks['A'],mature['A'],clicks['B'],mature['B'])
            safety = lab_stats.safety_effect(rows,p['theta'],p['safety_margin'])
            srm = lab_stats.assignment_quality(assigned['A'],assigned['B'])
            request_rows = await conn.fetch('''SELECT variant,COUNT(*)::int AS requests,
               COUNT(*) FILTER(WHERE error)::int AS errors,
               COUNT(*) FILTER(WHERE completed_at IS NULL)::int AS incomplete,
               percentile_cont(0.95) WITHIN GROUP(ORDER BY latency_ms) AS p95
               FROM lab_requests WHERE experiment_id=$1 AND received_at<=$2 GROUP BY variant''',eid,payload.watermark)
            bundle_rows = await conn.fetch('SELECT actual_card_count,COUNT(*)::int AS n FROM lab_bundles WHERE experiment_id=$1 AND planned_variant=\'B\' AND created_at<=$2 GROUP BY actual_card_count',eid,payload.watermark)
            bundles = {str(r['actual_card_count']):r['n'] for r in bundle_rows}
            completion = bundles.get('3',0)/sum(bundles.values()) if bundles else None
            operational = bool(request_rows) and all(not r['incomplete'] and r['p95'] is not None
                and p.get('p95_limit_ms') and r['p95']<=p['p95_limit_ms'] for r in request_rows)
            # A/A always renders A, so a three-card completion threshold does not apply.
            bundle_ok = d['kind']=='aa' or (completion is not None and p.get('minimum_bundle_completion') is not None and completion>=p['minimum_bundle_completion'])
            # Any failed request requires review; do not label absent error counts healthy.
            operational = operational and all(r['errors']==0 for r in request_rows)
            quality = (payload.data_complete and srm['status']=='pass' and operational and bundle_ok
                       and p.get('policy_checksum')==policy_checksum())
            last = await conn.fetchval('SELECT MAX(assigned_at) FROM lab_assignments WHERE experiment_id=$1',eid)
            final = bool(d['enrollment_closed_at'] and last and sum(mature.values())==sum(assigned.values())
                         and payload.watermark>=last+timedelta(hours=168)
                         and datetime.now(UTC)>=last+timedelta(hours=168+p['collection_grace_hours']))
            sample_ok = sum(assigned.values())>=p['total_users']
            practical = bool(effect and effect['p_value']<0.05 and effect['delta']>=p['minimum_effect']
                             and effect['ci_low']>p['minimum_ci_lower'])
            failures = (srm['status']=='fail' or any(r['errors'] for r in request_rows)
                        or any(p.get('p95_limit_ms') and r['p95'] is not None and r['p95']>p['p95_limit_ms'] for r in request_rows)
                        or p.get('policy_checksum')!=policy_checksum())
            quality_status = 'pass' if quality else 'fail' if failures else 'pending'
            ready = final and d['status']!='stopped'
            outcome = ('operational_stop' if d['status']=='stopped' else 'quality_inconclusive' if final and not quality
                       else 'interim' if not final else 'aa_complete' if d['kind']=='aa'
                       else 'inconclusive' if not sample_ok else 'adoption_supported' if practical and safety and safety['passed']
                       else 'safety_unconfirmed' if not safety or not safety['passed'] else 'keep_or_followup')
            result = dict(assigned=assigned,mature=mature,clicks=clicks,effect=effect,safety=safety,srm=srm,
                          requests=[dict(r) for r in request_rows],bundles=bundles,bundle_completion=completion,
                          quality_passed=quality,quality_status=quality_status,data_complete=payload.data_complete,operational_passed=operational,
                          bundle_passed=bundle_ok,final=final,decision_ready=ready,sample_ok=sample_ok,
                          outcome=outcome,sql_hash=hashlib.sha256(COHORT_SQL.encode()).hexdigest(),
                          next_action='데이터 품질 문제 조사' if failures else '최종 결정 기록' if ready else '모집·관찰 완료 대기')
            run = await conn.fetchrow('''INSERT INTO lab_analysis_runs(experiment_id,idempotency_key,config_hash,
               analysis_version,watermark,result) VALUES($1,$2,$3,$4,$5,$6::jsonb) RETURNING *''',
               eid,payload.idempotency_key,d['config_hash'],lab_stats.ANALYSIS_VERSION,payload.watermark,json.dumps(result,default=str))
            if ready and d['status']=='observing':
                await conn.execute("UPDATE lab_experiments SET status='ready' WHERE id=$1",eid)
            await audit(conn,eid,actor,'analysis',payload.reason,{'run_id':run['id'],'watermark':payload.watermark})
            return decode(run)


async def decision(eid,payload,actor):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            d = await conn.fetchrow('SELECT * FROM lab_experiments WHERE id=$1 FOR UPDATE',eid)
            run = await conn.fetchrow('SELECT * FROM lab_analysis_runs WHERE experiment_id=$1 ORDER BY id DESC LIMIT 1',eid)
            if not d or d['status']!='ready' or not run or run['id']!=payload.run_id:
                raise ValueError('최종 판정이 준비된 최신 스냅샷을 지정하세요.')
            result = decode(run)['result']
            if not result['decision_ready'] or run['config_hash']!=d['config_hash']:
                raise ValueError('품질·관찰 완료를 먼저 확인하세요.')
            if not result['quality_passed'] and payload.choice not in ('inconclusive','followup'):
                raise ValueError('품질 미결에서는 미결·후속 계획만 기록할 수 있습니다.')
            if payload.choice=='adopt' and (d['kind']!='ab' or result['outcome']!='adoption_supported'):
                raise ValueError('표본·효과·안전성 채택 기준을 모두 통과해야 합니다.')
            await audit(conn,eid,actor,'decision',payload.reason,{'run_id':run['id'],'choice':payload.choice})
            await conn.execute("UPDATE lab_experiments SET status='decided' WHERE id=$1",eid)


async def check_operational_alarm(request_id):
    """Fixed operational rules; does not inspect effectiveness or stop for significance."""
    async with get_pool().acquire() as conn:
        request = await conn.fetchrow('SELECT experiment_id FROM lab_requests WHERE request_id=$1',request_id)
        if not request:
            return None
        eid = request['experiment_id']
        severe = await conn.fetchval('''SELECT COUNT(*) FROM lab_requests WHERE experiment_id=$1
           AND completed_at>=NOW()-INTERVAL '5 minutes' AND error
           AND error_code IN ('preparation_failed','exposure_failed','request_failed')''',eid)
        recent = await conn.fetch('''SELECT variant,COUNT(*)::int AS n,
             COUNT(*) FILTER(WHERE error)::int AS errors FROM lab_requests WHERE experiment_id=$1
             AND completed_at>=NOW()-INTERVAL '15 minutes' GROUP BY variant''',eid)
        arms = {r['variant']:r for r in recent}
        rate_alarm = (set(arms)=={'A','B'} and all(r['n']>=100 for r in recent)
                      and arms['B']['errors']>=5
                      and arms['B']['errors']/arms['B']['n']-arms['A']['errors']/arms['A']['n']>=0.01)
    if severe>=3 or rate_alarm:
        try:
            await stop(eid,'고정 운영 경보: 5분 오류 3회 또는 군별 100요청 이상·B 실패 5회·오류율 +1%p','system')
            return 'stopped'
        except ValueError:
            return None  # A concurrent request may have stopped it already.
    return None

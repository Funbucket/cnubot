"""Shared stored-snapshot rendering for experiment delivery and signed QA."""
import asyncio
import json
import os
import logging
import time
import uuid
from datetime import timedelta

from app.database import get_pool
from app.services import experiment_lab as lab
from app.services import product_snapshot, promotion_preview, promotion_settings, promotions, recommendations, promotion_cards


async def student_pairs(user_id):
    snapshot = await asyncio.to_thread(product_snapshot.read)
    history = await recommendations.last_exposure_by_product(user_id, promotions.INLINE_CARD_SURFACE)
    pairs = promotion_preview.select_products(snapshot,os.getenv('TOSS_PUBLISHER_ID','').strip(),history)
    for _,product in pairs:
        product['snapshot_id'] = snapshot.get('updated_at')
        product['selection_mode']='student_bundle_v1'
        product['settings_revision']=promotion_settings.read_settings().revision
    return pairs


def prepare(pairs,metadata):
    """QA flag and origin are covered by the same HMAC as the destination."""
    urls = []
    for position,(key,product) in enumerate(pairs,1):
        promotions.TOSS_SHOPPING_PRODUCTS[key] = dict(product)
        snapshot = {k:product.get(k) for k in ('title','button_label','selection_mode','collection_id','settings_revision')}
        snapshot.update(metadata)
        token = promotions.create_tracking_token(
            metadata['user_id'],key,'menu_inline',target_url=product['url'],
            category_ids=product.get('category_ids') or [],taca_item_id=product.get('taca_item_id'),
            surface=promotions.INLINE_CARD_SURFACE,button_id='student_bundle_product',
            button_label='특가 바로가기',position=position,request_id=metadata['request_id'],product_snapshot=snapshot)
        urls.append(f'{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token={token}')
    output = (promotion_cards.create_inline_bundle_output([p for _,p in pairs],urls)
              if len(pairs)>1 else promotions.create_inline_product_output(pairs[0][1],urls[0]))
    return dict(pairs=pairs,output=output,metadata=metadata)


async def select(chosen,user_id,place):
    if lab.is_qa(user_id):
        return None
    key,product,_,request_id = chosen
    try:
        context = await lab.assign(user_id,place,request_id,'/cafeteria/menu')
    except RuntimeError:
        return None  # Database-less local mode has no experiments.
    if not context:
        return None
    metadata = {**context,'user_id':user_id,'bundle_id':str(uuid.uuid4()),'is_preview':False,
                'planned_variant':context['variant'],'rendered_policy':'current_single', 'fallback_reason':None}
    pairs = [(key,product)]
    try:
        if context.get('policy_checksum') != lab.policy_checksum():
            raise ValueError('Frozen policy checksum changed')
        if context['variant']=='B' and context['kind']=='ab':
            candidates = await student_pairs(user_id)
            if candidates:
                pairs = candidates
                metadata['rendered_policy']='student_bundle_v1'
                if len(pairs)<3:
                    metadata['fallback_reason']='insufficient_candidates'
            else:
                metadata['fallback_reason']='no_bundle_candidates'
        return prepare(pairs,metadata)
    except Exception:
        await finish(metadata,False,0,True,'preparation_failed')
        raise


async def record(delivery):
    metadata = delivery['metadata']
    items = []
    for position,(key,product) in enumerate(delivery['pairs'],1):
        items.append(dict(product_key=key,taca_item_id=product.get('taca_item_id') or 0,
                          category_ids=product.get('category_ids') or [],properties={
                            **{k:v for k,v in metadata.items() if k!='user_id'},
                            'position':position,'product_name':product['title'],
                            'price':product.get('price'),'original_price':product.get('original_price'),
                            'snapshot_id':product.get('snapshot_id'),'collection_id':product.get('collection_id'),
                            'actual_card_count':len(delivery['pairs']),
                            'selection_mode':metadata['rendered_policy']}))
    if metadata.get('is_preview'):
        return await recommendations.record_bundle_exposure(metadata['user_id'],'developer_bundle_preview',items,
                   metadata['request_id'],daily_cap=False)
    return await recommendations.record_bundle_exposure(metadata['user_id'],promotions.INLINE_CARD_SURFACE,items,
                   metadata['request_id'],daily_cap=True,lab_bundle={**metadata,'items':items})


async def finish(metadata,included,latency_ms,error=False,error_code=None):
    if metadata.get('is_preview'):
        return
    try:
        await get_pool().execute('''UPDATE lab_requests SET completed_at=NOW(),latency_ms=$2,
           error=COALESCE(error,FALSE) OR $3,response_included=$4,error_code=COALESCE(error_code,$5) WHERE request_id=$1''',
           metadata['request_id'],latency_ms,error,included,error_code)
    except Exception:
        logging.getLogger(__name__).exception("failed to finalize experiment delivery")


async def preview(eid,variant):
    developer = os.getenv('DEVELOPER_ID','').strip()
    if not developer:
        raise ValueError('비공개 환경 설정에 개발자 계정을 지정하세요.')
    d = await lab.get_design(eid)
    a = await promotions.get_inline_promotion_product(developer,str(uuid.uuid4()))
    if not a:
        return {'response':None,'reason':'유효한 A 후보가 없습니다.','is_preview':True}
    pairs = await student_pairs(developer) if variant=='B' else []
    pairs = pairs or [a]
    delivery = prepare(pairs,dict(user_id=developer,request_id=str(uuid.uuid4()),
                    experiment_id=eid,config_hash=d['config_hash'],planned_variant=variant,
                    rendered_policy='student_bundle_v1' if variant=='B' and len(pairs)>1 else 'current_single',
                    is_preview=True,preview_session_id=str(uuid.uuid4()),bundle_id=str(uuid.uuid4())))
    return {'response':{'version':'2.0','template':{'outputs':[delivery['output']]}},'is_preview':True,
            'scope':'학식 빈자리만 적용 · 직접 목록은 최대 6개 · 제휴 링크'}


async def reserve(eid,variant,actor):
    developer = os.getenv('DEVELOPER_ID','').strip()
    if not developer:
        raise ValueError('비공개 환경 설정에 개발자 계정을 지정하세요.')
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await lab.get_design(eid,conn)
            session = str(uuid.uuid4())
            await conn.execute('''INSERT INTO lab_preview_overrides(user_id,experiment_id,session_id,variant,expires_at)
                VALUES($1,$2,$3,$4,NOW()+INTERVAL '10 minutes') ON CONFLICT(user_id) DO UPDATE
                SET experiment_id=$2,session_id=$3,variant=$4,expires_at=NOW()+INTERVAL '10 minutes',created_at=NOW()''',developer,eid,session,variant)
            await lab.audit(conn,eid,actor,'preview_reserve','개발자 다음 적격 조회 1회',{'session_id':session,'variant':variant})
    return {'session_id':session,'expires_in_seconds':600}


async def pending(user_id):
    if not user_id or user_id!=os.getenv('DEVELOPER_ID','').strip():
        return False
    try:
        return bool(await get_pool().fetchval('SELECT 1 FROM lab_preview_overrides WHERE user_id=$1 AND expires_at>NOW()',user_id))
    except RuntimeError:
        return False


async def consume(chosen,user_id):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow('DELETE FROM lab_preview_overrides WHERE user_id=$1 AND expires_at>NOW() RETURNING *',user_id)
            if row:
                await lab.audit(conn,row['experiment_id'],'system','preview_consume','다음 적격 학식 조회에서 예약 소비',
                                {'session_id':row['session_id'],'variant':row['variant']})
    if not row:
        return None
    pairs = await student_pairs(user_id) if row['variant']=='B' else []
    pairs = pairs or [(chosen[0],chosen[1])]
    return prepare(pairs,dict(user_id=user_id,request_id=chosen[3],experiment_id=row['experiment_id'],
                    is_preview=True,preview_session_id=row['session_id'],planned_variant=row['variant'],
                    rendered_policy='qa',bundle_id=str(uuid.uuid4())))

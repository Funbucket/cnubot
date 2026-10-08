"""Reproducible IID scenarios, including random 50:50 arm sizes."""
from collections import Counter
import numpy as np
from app.database import get_pool
from app.services import experiment_lab as lab, lab_stats


def simulate(protocol):
    rng = np.random.default_rng(protocol['simulation_seed'])
    n,iterations = protocol['total_users'],protocol['simulation_iterations']
    baseline = protocol['baseline_rate']
    if not baseline:
        raise ValueError('현행 성숙 기준율을 먼저 입력하세요.')
    scenarios=[]
    for delta in sorted({protocol['minimum_effect'],protocol['target_effect'],0.0}):
        na=rng.binomial(n,0.5,iterations)
        nb=n-na
        a=rng.binomial(na,baseline)
        b=rng.binomial(nb,baseline+delta)
        significant=practical=0
        for (ca,cna,cb,cnb),count in Counter(zip(a.tolist(),na.tolist(),b.tolist(),nb.tolist())).items():
            effect=lab_stats.click_effect(ca,cna,cb,cnb)
            if effect and effect['p_value']<0.05 and effect['delta']>0:
                significant+=count
                if effect['delta']>=protocol['minimum_effect'] and effect['ci_low']>protocol['minimum_ci_lower']:
                    practical+=count
        scenarios.append(dict(true_delta=delta,significance_probability=significant/iterations,
                              practical_probability=practical/iterations))
    return dict(version='iid-random-allocation-v1',seed=protocol['simulation_seed'],iterations=iterations,
                baseline=baseline,total_users=n,scenarios=scenarios,
                note='IID 조건부 검정력. 안전성 공동 채택 확률·재고·효과 희석은 포함하지 않음.')


async def save(eid,actor):
    import asyncio
    design=await lab.get_design(eid)
    if design['status']!='draft':
        raise ValueError('시작 전 계획에서만 재산출할 수 있습니다.')
    result=await asyncio.to_thread(simulate,design['protocol'])
    result['config_hash']=design['config_hash']
    async with get_pool().acquire() as conn:
        await lab.audit(conn,eid,actor,'simulation','고정 계획의 표본·검정력 재산출',result)
    return result

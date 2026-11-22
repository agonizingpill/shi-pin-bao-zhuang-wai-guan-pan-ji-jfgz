from fastapi import HTTPException

from .disposition import finalize_decision, validate_review
from .inspection import audit, latest_grade, latest_measure, lot_row

REQUIRED_VOTES = 2


def vote_payload(vote):
    return {'voter': vote['voter'], 'stage': vote['stage'], 'grade': vote['grade'],
            'rework_units': vote['rework_units'], 'reason': vote['reason'], 'created_at': vote['created_at']}


def status(db, lot_id, username):
    """盲审进度。定案前不返回他人票内容，只返回进度与本人票。"""
    measure = latest_measure(db, lot_id)
    decision = latest_grade(db, measure['id']) if measure else None
    if not decision:
        return None
    votes = db.execute('SELECT * FROM blind_vote WHERE decision_id=%s ORDER BY id', (decision['id'],)).fetchall()
    initial = [vote for vote in votes if vote['stage'] == 'initial']
    if decision['state'] == 'blind':
        phase = 'arbitrating' if len(initial) >= REQUIRED_VOTES else 'collecting'
    elif decision['state'] == 'signed' and votes:
        phase = 'decided'
    else:
        return None
    scores = (decision.get('evidence') or {}).get('scores') or {}
    top = sorted(scores.values(), reverse=True)
    mine = next((vote for vote in votes if vote['voter'] == username), None)
    voted_initial = {vote['voter'] for vote in initial}
    return {'phase': phase, 'needed': REQUIRED_VOTES, 'received': len(initial),
            'margin': round(top[0] - top[1], 4) if len(top) >= 2 else None,
            'can_vote': phase != 'decided' and username not in voted_initial,
            'my_vote': vote_payload(mine) if mine else None,
            'votes': [vote_payload(vote) for vote in votes] if phase == 'decided' else None}


def cast_vote(db, lot_id, data, actor):
    lot = lot_row(db, lot_id, lock=True)
    measure = latest_measure(db, lot_id)
    decision = latest_grade(db, measure['id']) if measure else None
    if decision:
        prior = db.execute('SELECT * FROM blind_vote WHERE decision_id=%s AND voter=%s',
                           (decision['id'], actor)).fetchone()
        if prior:
            # 断线重试：同一票原样返回进度，不重复记票；内容不同视为改票，拒绝
            if (prior['grade'], prior['rework_units'], prior['reason']) == (data.grade, data.rework_units, data.reason):
                return status(db, lot_id, actor)
            raise HTTPException(409, '已登记盲审票，不能重复记票或更改')
    if lot['state'] != 'blind':
        raise HTTPException(409, '此批次不在盲审流程中')
    if not decision or decision['state'] != 'blind':
        raise HTTPException(409, '盲审已定案或尚未开始')
    if db.execute("SELECT 1 FROM defect_mark WHERE measure_id=%s AND state='open'", (measure['id'],)).fetchone():
        raise HTTPException(409, '当前样本还有待复核的缺陷标记')
    votes = db.execute('SELECT * FROM blind_vote WHERE decision_id=%s ORDER BY id FOR UPDATE',
                       (decision['id'],)).fetchall()
    initial = [vote for vote in votes if vote['stage'] == 'initial']
    stage = 'arbitration' if len(initial) >= REQUIRED_VOTES else 'initial'
    validate_review(lot, decision, data)
    db.execute('INSERT INTO blind_vote(decision_id,voter,stage,grade,rework_units,reason) VALUES (%s,%s,%s,%s,%s,%s)',
               (decision['id'], actor, stage, data.grade, data.rework_units, data.reason))
    audit(db, lot_id, actor, 'blind_vote_cast', decision_id=decision['id'], stage=stage)
    if stage == 'arbitration':
        # 两票分歧后，第三位主管一票定案
        finalize_decision(db, lot, decision, data.grade, data.reason, data.rework_units, actor,
                          'blind_review_decided', via='arbitration')
    elif len(initial) == REQUIRED_VOTES - 1:
        first = initial[0]
        if first['grade'] == data.grade and first['rework_units'] == data.rework_units:
            finalize_decision(db, lot, decision, data.grade, data.reason, data.rework_units, actor,
                              'blind_review_decided', via='agreement')
        else:
            audit(db, lot_id, actor, 'blind_review_split', decision_id=decision['id'])
    return status(db, lot_id, actor)

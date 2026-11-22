ALTER TABLE pack_lot DROP CONSTRAINT IF EXISTS pack_lot_state_check;
ALTER TABLE pack_lot ADD CONSTRAINT pack_lot_state_check CHECK (state IN
    ('new', 'blocked', 'measured', 'queued', 'review', 'blind', 'rework', 'approved', 'closed'));
ALTER TABLE grade_decision DROP CONSTRAINT IF EXISTS grade_decision_state_check;
ALTER TABLE grade_decision ADD CONSTRAINT grade_decision_state_check CHECK (state IN
    ('queued', 'predicted', 'failed', 'blind', 'signed'));
CREATE TABLE IF NOT EXISTS blind_vote (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    decision_id bigint NOT NULL REFERENCES grade_decision(id),
    voter text NOT NULL REFERENCES staff(username),
    stage text NOT NULL DEFAULT 'initial' CHECK (stage IN ('initial', 'arbitration')),
    grade char(1) NOT NULL CHECK (grade IN ('A', 'B', 'C')),
    rework_units integer CHECK (rework_units > 0),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (decision_id, voter)
);
CREATE INDEX IF NOT EXISTS blind_vote_decision ON blind_vote(decision_id);

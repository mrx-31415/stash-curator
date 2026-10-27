-- How strongly a Why these? flip disagrees with Curator: 'mild' (Not that
-- good / Could be OK, a slight dislike or like) or 'strong' (Not for me / I'd
-- really like this, a thumb). Earlier flips were all mild. Unflipped answers
-- keep the default; it does not apply to them.
ALTER TABLE scene_reason_answer
    ADD COLUMN flip_strength TEXT NOT NULL DEFAULT 'mild' CHECK (flip_strength IN ('mild', 'strong'));

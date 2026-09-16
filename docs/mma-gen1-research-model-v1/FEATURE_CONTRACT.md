# UFC Gen 1 feature contract

Each modeling row is one decisive UFC bout with the fighters ordered by stable
source fighter ID.  Every rolling value is emitted before the target bout is
applied to fighter state.  Reversing a requested participant order returns the
complement of the canonical probability; it does not create a separately scored
row.

The source contains finalized historical records with event dates at day
resolution.  It does not contain historical publication revisions.  The study is
therefore reconstructed historical development, not certified point-in-time
forecast evidence.  Modern-era data has no fighter appearing twice on one event
date, removing the only material ambiguity created by day-only timestamps.

The model uses 25 numeric features and one weight-class category: chronological
Elo, experience, prior win/finish/KO/submission/recent-form rates, layoff,
historical duration, striking, takedown, submission, control and knockdown rates,
prior opponent Elo, weight-class changes, rematches, scheduled rounds and calendar
year.  Rates use only prior decisive fights and contain explicit cold-start/layoff
missingness.

The following source fields are never pre-bout features: target result, method,
round, duration or target statistics; `Fighters Stats.csv`; current fighter-page
W/L/D and belt; final all-history ratings; odds; rankings; weigh-ins; injuries;
and short-notice status.  Date of birth is absent, so age is unsupported.  Height,
reach and stance are current snapshots without historical vintages and are
excluded from Gen 1 despite their apparent face validity.

Probability means `P(canonical fighter A wins | decisive result, reconstructed
pre-bout history)`. Draws and no contests are outside this binary probability and
must not be settled as losses.

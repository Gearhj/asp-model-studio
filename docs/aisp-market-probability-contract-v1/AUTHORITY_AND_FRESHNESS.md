# Authority and freshness boundary

Model Studio owns the immutable forecast population and its numerical provenance. This contract adds a deterministic view over that population. It grants no new forecasting, model-promotion, sportsbook, market-selection, decision, wagering, staking, account, scheduler, or AISP-write authority.

AISP must verify that the requested market binds the intended event and exact forecast revision. It must independently enforce quote timestamps, consumer horizon, import state, experiment authority, decision deadline, settlement rules, and any paper or funded policy. An old but intact forecast remains old; deriving a new line probability does not refresh its source cutoff or creation clock.

Supported status means only that the arithmetic is directly available from the named population. It does not mean the forecast is current, the quote is compatible, the event is eligible, the model is promoted, or the market has positive expected value.

Model limitations remain attached:

- MLB V18 needs confirmed final inputs for its controlling forecast and retains uncertified historical chronology.
- NFL M1’s tie mass is a discrete residual-model outcome, not a separately validated tie model; named personnel and injuries are missing.
- NBA point/Elo has no distribution. NBA joint output is a separate research channel with known close-margin limitations.
- CFB Ridge-margin, Elo, and joint winner probabilities are separate; CFB remains research-only.

The library has no filesystem or network access. A sport adapter must first verify package bytes, population counts, identities, and hashes. A hash or count disagreement is an error, never a fallback.

# CFB virtual paper eligibility supplements

`server.sports_cfb_gen1.paper_eligibility.publish_eligible` is a local phase of
the existing locked CFB owner. It makes no provider calls, loads no fitted model,
does not simulate, and makes no AISP writes. Installation remains the existing
owner's supported operation.

Call it after the owner tick returns its immutable `runner['discovery']`, while
the same publisher lock is held:

```python
paper = publish_eligible(
    discovery_ref=runner['discovery'], release_ref=release_ref,
    grant_ref=release['paperEligibilityAuthorization'],
    exchange_family_root=Path(exchange_root).parent / 'cfb-gen1-research-v1',
    output_root=state / 'paper-eligibility', clock=clock,
)
```

The release must bind the exact separately retained
`CFB_VIRTUAL_POLICY_EXTENSION_AUTHORIZATION_V1` grant. It must match the existing
acquisition plan's physical SHA, the selected numerical configuration and the
original single-game policy. The supplement's `summaries.authorization` is the
original policy object unchanged. `summaries.authorizationScope` carries the
physical extension grant, expiry and required current discovery/consumer gates.
The grant expires at its exact `validUntilUtc`; it is never extended by a tick.

Only a currently eligible discovery row with an unexpired lease can be used.
Every package, forecast, population and original publication receipt is verified.
The CFBD game ID, baseline probabilities, model SHA, source cutoff, creation time
and original discovery receipt's `committedAtUtc` are preserved. The selected
model may use `sha256` or `physicalSha256`; the binding records its exact value.
Ridge and Elo remain separate from the controlling paired residual joint channel.

New supplements are prepared outside the discoverable object directory and
atomically committed before kickoff minus 30 minutes. Lease, grant expiry and
cutoff are checked immediately before that commit. Existing valid supplements
are reused with the same bytes and publication clock during an independently
revalidated consumer window. A started game is never reused as current evidence.
Previous single-game supplements are preserved. New forecast revisions get new
supplement identities. No current lease is created or renewed here.

Delivery uses the existing `AISP_RESEARCH_SUPPLEMENT_V1` contract,
`ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1` artifact and
`PAPER_RESEARCH_ELIGIBILITY` kind under
`cfb-gen1-research-v1/paper-eligibility/sha256/<address>/`. Encoding is canonical
UTF-8 (`ensure_ascii=False`, sorted keys, compact separators, no NaN). Address is
SHA-256 of canonical manifest **without** `supplementSha256`; manifest physical
SHA is separately reported. Per-package failures are isolated and retained in
the returned owner receipt; `exitCode=1` requires the owner to report the phase
failure. Producer publication does not prove consumer import or position authority.

Focused validation uses synthetic packages and authorization fixtures:

```powershell
python -m pytest tests/test_cfb_paper_eligibility.py tests/test_multisport_paper_research_eligibility.py -q
```

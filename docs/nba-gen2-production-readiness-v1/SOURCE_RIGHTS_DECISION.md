# NBA Gen2 team-box source decision

Reviewed 2026-09-17 before any team-box acquisition.

## NBA.com Stats: rejected for this use

The current NBA.com Terms of Use, section 9, limits NBA Statistics to legitimate
news reporting or private, non-commercial purposes and expressly prohibits use
in connection with gambling activity. It also restricts a comprehensive,
regularly updated statistics database without prior consent. The NBA Stats FAQ
states that its statistics are not available for download for academic or
personal use.

ASP Model Studio supplies model evidence to AISP, which includes wagering and
position workflows. That intended downstream use conflicts with the published
NBA.com terms. The authorized NBA.com request budget therefore remains unused:
zero endpoint calls, zero response bytes, and zero cost. The maintained
`nba_api` package would only wrap the same NBA.com endpoints and would not
change the data authority or terms.

Sources reviewed:

* https://www.nba.com/termsofuse (last updated 2026-07-13)
* https://www.nba.com/stats/help/faq
* https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguegamelog.md

## Selected zero-cost alternative

Use the retained SportsDataverse `hoopR-nba-data` team-box exports derived from
ESPN. At retained publisher revision
`ec432186c9aa08ef1267578f0e54ccf50f510452`, its license expressly applies CC
BY 4.0 to data, code, and documentation. It permits retention, adaptation,
internal modeling, and commercial use with attribution and disclosure of
changes. No separate restriction on derived forecasts was found.

The initial acquisition is limited to eight season files, 2018-19 through
2025-26, from the `espn_nba_team_boxscores` release. Raw files remain private
under `C:\Users\james\asp-data-staging\nba\gen2-team-box-v1`. This is Category
A reconstructed historical evidence. Retrieval on 2026-09-17 does not certify
historical publication vintages.

Attribution: NBA team game box-score facts published by SportsDataverse/hoopR
authors, derived from ESPN, under CC BY 4.0. ASP Model Studio filters scope,
reconciles identities, derives chronological features, and fits independent
models. Changes are disclosed and no publisher endorsement is implied.


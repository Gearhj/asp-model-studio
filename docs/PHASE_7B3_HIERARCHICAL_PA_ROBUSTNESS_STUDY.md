# Phase 7B3 — Hierarchical PA model robustness study

## Terminal research decision

**A. KEEP_DIRECT_8_CLASS**

The small improvement from the previously fitted raw Extra Trees hierarchy did
not survive development-only model and calibration selection. The selected
Gold binary Logistic (`C=0.01`) plus isotonic calibration was worse than the
direct Gold Logistic on 2024 binary log loss and eight-class log loss. The
paired whole-game bootstrap favored the selected hierarchy in only 15.7% of
replicates and its 95% interval crossed zero.

This is a research-only result. No model was promoted.

## Frozen authorities and scope

- Starting commit: `a9eef89a30e238ecb118c57e2e031ba928946454`
- Study branch: `phase7b3-hierarchical-model-robustness`
- Gold dataset: `gold-table:gold_mlb_pa_v1:sha256:56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0`
- Matched development population: 536,102 rows, seasons 2021–2023
- Matched validation population: 180,711 rows, season 2024
- Full governed validation population: 182,449 rows
- Governed unmatched population retaining Base Logistic: 1,738 rows
- Target: `OUT = {STRIKEOUT, BIP_OUT}`; all other governed classes are
  `NOT_OUT`
- Frozen eight-class order: `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`,
  `SINGLE`, `DOUBLE`, `TRIPLE`, `BIP_OUT`, `OTHER_REACH`

Bronze, Silver, and Gold were not rebuilt. No features or data sources were
added. No 2025 data was opened.

## Development-only selection

The two fixed expanding-window folds were:

1. train 2021 (178,522 rows), validate 2022 (175,508 rows);
2. train 2021–2022 (354,030 rows), validate 2023 (182,072 rows).

The combined OOF selection population was 357,580 rows. Every fold fitted its
preprocessor only on that fold's training rows. No 2024 row was used for model
or calibrator selection.

### Development OOF binary leaderboard

| Rank | Candidate | OOF log loss | Brier | ECE | ROC-AUC | PR-AUC | Fit s | Score s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Gold Logistic C=0.01 | 0.6288050684963835 | 0.21857618446657423 | 0.008646412276815733 | 0.5400913911160342 | 0.7010182137560966 | 19.699 | 0.073 |
| 2 | Gold Logistic C=0.05 | 0.6288136100011223 | 0.21857973640984946 | 0.008762589348909762 | 0.5401024120527084 | 0.7010158485657807 | 24.390 | 0.073 |
| 3 | Gold Logistic C=0.20 | 0.6288157645835274 | 0.218580647414857 | 0.008748135521862361 | 0.5401027730191719 | 0.7010145427204201 | 34.496 | 0.066 |
| 4 | Gold Logistic C=1.00 | 0.628816382270493 | 0.21858090777535957 | 0.008764450373493306 | 0.5401028817689181 | 0.701014124226427 | 24.834 | 0.066 |
| 5 | Gold HGB lr=0.05, leaves=15 | 0.6288264218271894 | 0.21857733159837872 | 0.00735982007813516 | 0.5379016782619241 | 0.6997284516472833 | 19.466 | 4.020 |
| 6 | Gold Extra Trees sqrt, leaf=100 | 0.6288866811758871 | 0.21862004364510143 | 0.0023001057134379127 | 0.5357434088232623 | 0.6974280315762492 | 341.596 | 12.102 |
| 7 | Gold Extra Trees 0.5, leaf=100 | 0.6289037038563543 | 0.2186190346375482 | 0.0056411248819668415 | 0.5360466773978476 | 0.6985801309069931 | 1042.375 | 14.260 |
| 8 | Gold Extra Trees sqrt, leaf=20 | 0.6289383663836149 | 0.21863660933562395 | 0.0045243434665881615 | 0.5350647863469594 | 0.6973929471672259 | 388.028 | 17.441 |
| 9 | Collapsed direct Gold Logistic | 0.628945617311096 | 0.2186303117382936 | 0.009341945744855034 | 0.5395832919131861 | 0.7008551498072527 | 158.778 | 0.286 |
| 10 | Gold HGB lr=0.05, leaves=31 | 0.6292774797075398 | 0.21877528705256394 | 0.008752088002214631 | 0.5357932952119016 | 0.6984106836697828 | 22.957 | 3.944 |
| 11 | Gold HGB lr=0.10, leaves=15 | 0.6294786489055871 | 0.21885569888602785 | 0.011822922197706663 | 0.5361087885803569 | 0.6983985502904603 | 16.664 | 3.456 |
| 12 | Gold Extra Trees 0.5, leaf=20 | 0.629653139035395 | 0.21894020263681674 | 0.012067645891019474 | 0.5333534224578376 | 0.6971979218413047 | 1167.167 | 22.098 |
| 13 | Gold HGB lr=0.10, leaves=31 | 0.6308386729888688 | 0.21944968340241114 | 0.01721255624396338 | 0.5312907957477084 | 0.6956354062644443 | 19.674 | 3.569 |

### Calibration comparison

The best raw candidate from each family was evaluated raw, with Platt
calibration, and with isotonic calibration. Calibrators were fitted only on
the combined development OOF predictions.

| Rank | Family winner | Calibration | OOF log loss | Brier | Intercept | Slope | ECE |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Logistic C=0.01 | isotonic | 0.628294395944614 | 0.21836599794971684 | 4.4769e-09 | 0.9999999929 | 1.1426e-16 |
| 2 | Collapsed direct | isotonic | 0.6283415803024183 | 0.218385972305557 | 4.5179e-09 | 0.9999999928 | 1.0759e-16 |
| 3 | HGB lr=0.05, leaves=15 | isotonic | 0.6283853917266229 | 0.21839999585266864 | 3.8038e-09 | 0.9999999939 | 8.7039e-17 |
| 4 | Logistic C=0.01 | Platt | 0.6284752196275921 | 0.21844255808605006 | 2.7001e-08 | 0.9999999905 | 0.001599002706832641 |
| 5 | Collapsed direct | Platt | 0.6285662900199326 | 0.2184816433629834 | -1.6960e-09 | 1.0000000028 | 0.0013511711110153705 |
| 6 | HGB lr=0.05, leaves=15 | Platt | 0.6285942145312149 | 0.2184897178180156 | -6.3227e-10 | 1.0000000009 | 0.0016909209296086486 |
| 7 | Extra Trees sqrt, leaf=100 | isotonic | 0.6286341544915558 | 0.21851096678205387 | 5.7887e-11 | 0.9999999999 | 2.7606e-17 |
| 8 | Logistic C=0.01 | raw | 0.6288050684963835 | 0.21857618446657423 | 0.20826975019049088 | 0.7219636027427208 | 0.008646412276815733 |
| 9 | HGB lr=0.05, leaves=15 | raw | 0.6288264218271894 | 0.21857733159837872 | 0.18456155020922013 | 0.7481672305137193 | 0.00735982007813516 |
| 10 | Extra Trees sqrt, leaf=100 | Platt | 0.6288853685666397 | 0.21861874840561724 | -8.1721e-10 | 1.0000000012 | 0.0027588361807215963 |
| 11 | Extra Trees sqrt, leaf=100 | raw | 0.6288866811758871 | 0.21862004364510143 | -0.018103253265766815 | 1.0218660504431007 | 0.0023001057134379127 |
| 12 | Collapsed direct | raw | 0.628945617311096 | 0.2186303117382936 | 0.22295630084260484 | 0.7038565605159854 | 0.009341945744855034 |

The selected Logistic `C=0.01` plus isotonic calibrator was frozen under
selection-record SHA-256
`1ae35c0bcce4a989660341ef7fd210869c32ee8a43c7ad7e5f64897404a7c9bd`
before 2024 scoring. The underlying Logistic was then refitted on all 536,102
matched development rows.

## Matched 2024 comparison

| Model | 8-class LL | Summed Brier | ECE | Accuracy | Macro-F1 | Binary LL | Binary Brier | Cal intercept | Cal slope | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct Gold Logistic | 1.4778808498644482 | 0.7040277515790683 | 0.001438315874177647 | 0.4534035006170073 | 0.09332003157919234 | 0.6260184989390155 | 0.21726304253867965 | 0.1863528221945934 | 0.792237619034738 | 0.5403327425278722 | 0.7055337589403281 |
| Initial raw Extra Trees hierarchy | 1.4776061122808983 | 0.7039246939722101 | 0.0023102359301853826 | 0.45337583212975413 | 0.09258057766795164 | 0.6257437613554654 | 0.21713700628955307 | -0.2690265293003208 | 1.4142584894662518 | 0.5404894077892547 | 0.7056715123050166 |
| Selected Logistic+isotonic hierarchy | 1.478371366423092 | 0.7039235788019654 | 0.002019706263713876 | 0.4534035006170073 | 0.09271638299936877 | 0.6265223741806278 | 0.21715653717893169 | 0.12977105574899894 | 0.8521515845426278 | 0.5400692570152361 | 0.7047742085113986 |

Selected-minus-direct eight-class log-loss difference was
`+0.0004905165586437388`; positive favors the direct eight-class model. The
reconstructed probabilities preserved the frozen class order, were finite and
nonnegative, summed to one with maximum error `4.440892098500626e-16`, and
preserved within-group ratios with maximum error
`3.3306690738754696e-16`.

## Full governed 2024 population

All 182,449 rows were evaluated: selected hierarchy on 180,711 matched rows
and governed Base Logistic on all 1,738 unmatched rows. No row was omitted.

| Model | Log loss | Summed Brier | ECE | Accuracy | Macro-F1 |
|---|---:|---:|---:|---:|---:|
| Governed Base Logistic | 1.4827332596445002 | 0.7061395390730664 | 0.003112544507234644 | 0.45242232075812966 | 0.08640780054871053 |
| Selected hierarchy matched + Base unmatched | 1.4784692514388824 | 0.7039769065411957 | 0.0019835662272701883 | 0.45338149291034757 | 0.0926770036493561 |

The hybrid-minus-Base full-population log-loss difference was
`-0.004264008205617786`. This comparison does not make the selected hierarchy
better than Direct Gold on the matched population; it reflects that the
matched Gold feature model is stronger than the all-row Base reference.

## Paired whole-game bootstrap

- 2,000 replicates over 2,409 whole-game clusters; seed `20260819`
- difference convention: selected hierarchy minus Direct Gold; negative favors
  the hierarchy
- mean: `+0.00048199774906755767`
- median: `+0.00042768679761292204`
- 95% interval: `[-0.0002700105967464367, +0.0015442480520882931]`
- replicates favoring hierarchy: `15.7%`

## Stability slices

Positive differences favor Direct Gold.

| Group | Slice | Rows | Direct LL | Selected hierarchy LL | Difference |
|---|---|---:|---:|---:|---:|
| Month | 2024-03 | 4,258 | 1.5064416369423543 | 1.5067520549347293 | +0.00031041799237496726 |
| Month | 2024-04 | 29,509 | 1.4738602291741725 | 1.4746930056906689 | +0.0008327765164963807 |
| Month | 2024-05 | 30,247 | 1.4684530076568023 | 1.468285468717344 | -0.00016753893945842258 |
| Month | 2024-06 | 29,822 | 1.4782797589267216 | 1.4802429674805648 | +0.001963208553843243 |
| Month | 2024-07 | 27,855 | 1.4841869535738255 | 1.4840812273199264 | -0.00010572625389904111 |
| Month | 2024-08 | 30,298 | 1.4845568997631498 | 1.4849619338673898 | +0.00040503410424008734 |
| Month | 2024-09 | 28,722 | 1.4741336478282256 | 1.4741315449841834 | -0.000002102844042228824 |
| Season type | Regular season | 180,711 | 1.4778808498644482 | 1.478371366423092 | +0.0004905165586437388 |
| Season type | Postseason | 0 | — | — | not estimable |
| Batter seen | Seen in matched 2021–2023 | 168,981 | 1.4787664366918223 | 1.4791321267579571 | +0.00036569006613484945 |
| Batter seen | Unseen in matched 2021–2023 | 11,730 | 1.4651231902159783 | 1.4674119425402419 | +0.002288752324263621 |
| Pitcher seen | Seen in matched 2021–2023 | 159,391 | 1.476364486079446 | 1.477014751173288 | +0.0006502650938420285 |
| Pitcher seen | Unseen in matched 2021–2023 | 21,320 | 1.4892173761334557 | 1.4885135925619988 | -0.0007037835714569507 |
| Batter history | Low, <100 prior PA | 8,984 | 1.472309643427837 | 1.474634712357956 | +0.0023250689301188565 |
| Batter history | High, >=100 prior PA | 171,727 | 1.4781723108381246 | 1.4785668516998465 | +0.0003945408617218593 |
| Pitcher history | Low, <250 prior BF | 29,492 | 1.4893672162085982 | 1.4919847794225078 | +0.0026175632139096017 |
| Pitcher history | High, >=250 prior BF | 151,219 | 1.4756406821856398 | 1.4757163642330313 | +0.00007568204739150097 |

Only three of seven monthly slices and the unseen-pitcher slice favored the
selected hierarchy. The selected hierarchy was worse in both low-history
slices and for unseen batters.

## Evidence and verification

The request-addressed research artifact is stored outside Git at:

`C:\Users\james\asp-data-staging\mlb-gold-v1\hierarchical-studies\sha256\a83f01937b0f16e0402a950417d5a882d32424644f208820039d2fb8b642575f`

- Study SHA-256: `a83f01937b0f16e0402a950417d5a882d32424644f208820039d2fb8b642575f`
- Machine results SHA-256: `60eb887b6ec514b5d14a9520734493425c56522095001d51315b4f5540084117`
- Human report SHA-256: `2f3c292b983da1e2a4ccb0c3698b9b11f38f6b355dde1c21e4b9c4d1ee2b01ec`
- Bootstrap replicate SHA-256: `5bebcefb67046703ee5a6afa91a0dfa0e60d41b60623be20d0807bc05300634f`
- Final focused suite: 20 passed, 0 failed, 0 errors
- Study elapsed time: 3,451.34 seconds
- Promotion requested: false
- Promotion performed: false

Large OOF, matched-validation, full-population prediction arrays, the selected
underlying model, and calibrator are stored only under the external
request-addressed artifact root. No large artifact or data file is committed.

# Vahan raw coverage (2026-11-01)

Goal: monthly two-wheeler registrations by maker (electric, at minimum Ola Electric),
raw under `D:\RealityEngine\raw\vahan`, as far back as the public dashboard allows.

## What blocked the obvious route

`https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml` (VAHAN 4,
PrimeFaces 8 / JSF) **does not serve a month-wise table any more**. Tested with a
scripted browser-equivalent session: GET the page, replay the dashboard's own staged
AJAX changes (`yaxisVar=Maker`, `xaxisVar=Month Wise`, `selectedYearType=C`,
`selectedYear=2026`), then the Refresh button's partial request. The server answers:

```xml
<partial-response id="j_id1">
  <error>
    <error-name>class javax.faces.el.EvaluationException</error-name>
    <error-message><![CDATA[Not supported yet.]]></error-message>
  </error>
  <changes><eval><![CDATA[PF('reportTable').paginator.setPage(0);]]></eval></changes>
</partial-response>
```

No `combTablePnl` update is rendered; the `reportTable` widget the response references
never exists on the page. The same failure occurs for every Month Wise combination tried
(Y = Maker, Vehicle Category, Vehicle Class; year type Calendar, Financial, Till Today),
so it is a server-side unimplemented branch ("Not supported yet." is NetBeans' generated
`UnsupportedOperationException` stub), not a client or rate-limit issue. The page's
Vehicle Category filter also lists only the four-wheeler codes (`4WIC`, `LMV`, `MMV`,
`HMV`), so even the working `Maker x Vehicle Category Group` report is 4W-only.

The JSF page was left alone; no data can be taken from the Month Wise path without the
operator deploying that method.

## What does work

`https://analytics.parivahan.gov.in/analytics/publicdashboard/vahan` is the public
analytics dashboard for the same VAHAN registrations and serves JSON. Three endpoints
are used:

| endpoint | parameters | returns |
|---|---|---|
| `lazy/vehicle-makers` | `page`, `size`, `search` | maker names (7,775 in total) |
| `vahandashboard/top5Makerchart` | same filters as the table | top-5 makers for the filter |
| `vahandashboard/durationWiseRegistrationTable` | `calendarType=3` gives one row per month; `calendarType=1/2/4` yearly/quarterly; filters `vehicleMakers`, `vehicleFuels` (repeatable), `vehicleCategoryGroup`, `evType`, `stateCode`, `rtoCode`, `fromYear`, `toYear` | `[{"yearAsString":"2026-October","registeredVehicleCount":11610}]` |

The observation range (`fromYear`/`toYear`) is ignored by the monthly view: it returns
the full held history (1950-01 onward for some makers), which is exactly the "as far back
as the dashboard allows" ask. `evType` does not accept a list; the fuel filter
`vehicleFuels` is repeatable and covers both EV codes (`PURE EV`, `ELECTRIC(BOV)`).
`vehicleMakers` matches case-insensitively.

## Fetcher

`reality_engine/scripts/fetch_vahan_raw.py` — small, raw-only, no DB writes, resumable.

```bash
python -m reality_engine.scripts.fetch_vahan_raw          # dashboard top-5 EV 2W makers
python -m reality_engine.scripts.fetch_vahan_raw --makers "OLA ELECTRIC TECHNOLOGIES PVT LTD"
python -m reality_engine.scripts.fetch_vahan_raw --all-makers   # 7,775 names, ~1 h at 0.5 s
python -m reality_engine.scripts.fetch_vahan_raw --check  # offline consistency check
```

Output under `D:\RealityEngine\raw\vahan`:

- `top5_2w_ev.json` — the dashboard's top-5 payload (raw)
- `monthly_2w_ev/<maker>.json` — one raw monthly payload per maker
- `monthly_2w_ev_by_maker.csv` — combined `maker, month, registrations` view (derived)
- `_manifest.csv` — maker, status, months, range, total, bytes, seconds, fetched_at

`--check` asserts every held file parses, months are `YYYY-MM` newest-first, and each
maker's monthly sum equals the top-5 total for the same filter. It also prints a sample row.
`python -m unittest reality_engine.tests.test_vahan_raw` covers the month parser and the
file-safe maker slug offline.

## Coverage of the run (2026-11-01)

2,008 monthly rows, 5 makers, 1982-09..2026-10 (the start is each maker's first EV 2W
month; the API returns much older sparse rows for some makers and they are kept).

| maker | months | range | total EV 2W | sample |
|---|---:|---|---:|---|
| TVS MOTOR COMPANY LTD | 530 | 1982-09..2026-10 | 1,261,147 | 2026-10 = 58,412 |
| OLA ELECTRIC TECHNOLOGIES PVT LTD | 59 | 2021-12..2026-10 | 1,147,286 | **2026-10 = 11,610** |
| BAJAJ AUTO LTD | 922 | 1950-01..2026-10 | 990,824 | 2026-10 = 46,648 |
| ATHER ENERGY LTD | 98 | 2018-09..2026-10 | 834,053 | 2026-10 = 30,368 |
| HERO MOTOCORP LTD | 399 | 1993-08..2026-10 | 373,838 | 2026-10 = 28,737 |

Sample raw row (Ola Electric, first row of
`monthly_2w_ev/ola_electric_technologies_pvt_ltd.json`):

```json
{"year": 0, "yearAsString": "2026-October", "registeredVehicleCount": 11610, "monthlyCountList": null}
```

The five monthly sums equal the dashboard's own top-5 totals exactly (`--check`: 5/5
matched), which cross-validates the month split against an independent endpoint.

## Limits and rate

- The dashboard's own maker view is top-5 only; per-maker monthly data needs one request
  per maker. The default fetcher covers those five (Ola included); `--all-makers` is
  opt-in because the list has 7,775 names and that is 7,775 requests to a government site.
- Measured response times: 0.02–0.11 s per JSON request, no 429/5xx observed. The
  fetcher sleeps 0.5 s between makers (≈2 requests/s ceiling) and retries 429/5xx with
  exponential backoff.
- Vahan registrations are retail registrations by maker, not despatches or deliveries;
  the two differ for Ola. EV is `PURE EV` + `ELECTRIC(BOV)` only (hybrids are separate
  fuel codes and are not included).
- The legacy JSF page cannot be used for 2W at all (4W-only category filter); do not
  point a future fetcher at `vahan4dashboard` expecting 2W data.

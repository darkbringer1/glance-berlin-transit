# Data source and model

Checked on 3 November 2026.

## Source

[BVG REST API](https://v6.bvg.transport.rest) by [derhuerst](https://github.com/derhuerst) (hafas-rest-api over BVG/VBB data). Public, no key, unofficial: not run by BVG. Limit 100 requests per minute; one refresh makes 9 requests (one per hub). Change the base URL with `BVG_API`, for example to a self-hosted hafas-rest-api.

## Request

```
GET {BVG_API}/stops/{hub}/departures?duration=30&results=80&remarks=true&bus=false&tram=false&regional=false&express=false&ferry=false
User-Agent: glance-berlin-transit/1.0
```

| Hub | Stop id |
|---|---|
| S+U Alexanderplatz | 900100003 |
| S+U Friedrichstraße | 900100001 |
| U Hermannplatz | 900078101 |
| S+U Zoologischer Garten | 900023201 |
| U Nollendorfplatz | 900056102 |
| S Ostkreuz | 900120003 |
| S Südkreuz | 900058101 |
| S+U Hermannstraße | 900079221 |
| S+U Gesundbrunnen | 900007102 |

## Fields read

```
departures[]
  .line.name            "U8", "S41"; only the 25 lines in LINES are kept
  .cancelled            true when the departure is cancelled
  .delay                seconds, null when no realtime data
  .remarks[]
    .type               only "warning" is used
    .summary / .text    German text, shown as is (HTML-escaped)
    .validFrom / .validUntil   ISO times; the warning must be active now
    .id                 de-duplicates the same warning seen at several hubs
```

## Output

The service returns an HTML fragment for a Glance `extension` widget, with the headers Glance expects (`Widget-Title`, `Widget-Content-Type: html`). Internally, per line:

```
{"state": "bad" | "warn" | "ok" | "none", "delay": <median minutes, 0 below 2>, "cancelled": <count>}
```

plus the list of active warnings and how many hubs answered.

## Caching

Results stay fresh for `CACHE_SECONDS` (300). After a failed refresh it waits `RETRY_SECONDS` (120) and keeps showing the last good copy with its time. Nothing is written to disk and no request data is logged.

# Crustdata API notes (x-api-version 2025-11-01)

Collected from docs.crustdata.com on 22 Nov 2026. The `json` shapes below are condensed from the docs. Anything marked UNVERIFIED should be checked with a live call before you rely on it.

Base `https://api.crustdata.com`. Headers: `authorization: Bearer <key>`, `x-api-version: 2025-11-01`, `content-type: application/json`.
Every response except a 429 refused before reaching the API carries `X-Credits-Used` (decimal string).
Error body (most endpoints): `{"error": {"type": ..., "message": ..., "metadata": []}}`. Web and identify return a 401 as `{"message": "Invalid API key in request"}`.
Free endpoints: GET /account/credits and GET /account/endpoints.

| Endpoint | Default RPM | Credits |
|---|---|---|
| POST /company/identify | 30 | 0.2 per identifier that matches (unmatched identifiers are free) |
| POST /company/enrich | 15 | 2 per company (technographics +2, social_posts +5) |
| POST /company/search | 30 | 0.03 per result + premium field groups |
| POST /job/search | 30 | 0.03 per result |
| POST /web/search/live | 10 | 1 per page |
| POST /web/enrich/live | 10 | 1 per page (per URL? UNVERIFIED) |
| watch create/manage | 10 per path | per notification |

## /company/identify
Request: `{"names": ["Acme Leathers"]}`, or `domains` / `crustdata_company_ids` / `professional_network_profile_urls` (exactly one key, 1–25 values). Optional `exact_match`.
Response is an array, one item per identifier:
```json
[{"matched_on":"serverobotics.com","match_type":"domain","matches":[{"confidence_score":1,
  "company_data":{"crustdata_company_id":628895,"basic_info":{"name":"Serve Robotics",
  "primary_domain":"serverobotics.com","employee_count_range":"51-200","industries":["..."],
  "website":"...","professional_network_url":"...","year_founded":"...","company_type":"..."}}}]}]
```
No match comes back as HTTP 200 with `matches: []`. The OpenAPI spec also defines a 404, so handle both.

## /company/enrich
Request: `{"domains": ["retool.com"], "fields": ["basic_info","headcount","locations","taxonomy","revenue","news"]}`. Only one identifier type per request. Without `fields` you get basic_info only.
Response: an array with the same shape as identify. The data sits under `matches[].company_data`:
- `headcount.total`, `headcount.timeseries[] {date, employee_count}` (date string; format UNVERIFIED), `headcount.growth_percent.{mom,qoq,six_months,yoy}`, `headcount.largest_headcount_country`, `headcount.by_region_absolute`
- `locations.country`, `.state`, `.headquarters`, `.street_address`, `.all_office_addresses[]`
- `taxonomy.professional_network_industry`, `.professional_network_industries[]`, `.categories[]`, `.primary_naics_detail.{naics_code,sector,industry}`
- `revenue.estimated.{lower_bound_usd, upper_bound_usd}`
- `news[].article_publish_date` (plus title/url — check a live response)
- top-level `updated_at`, `indexed_at`; growth as-of date `metadata.growth_calculation_date`

## /job/search
```json
{"filters":{"op":"and","conditions":[
   {"field":"company.basic_info.crustdata_company_id","type":"=","value":631394},
   {"field":"metadata.date_added","type":"=>","value":"2026-05-01"}]},
 "fields":["job_details.title","job_details.url","location.raw","location.city","metadata.date_added"],
 "sorts":[{"field":"metadata.date_added","order":"desc"}],"limit":50}
```
Response: `{"job_listings":[{"job_details":{"title","url"},"location":{"raw","city","state","country"},"metadata":{"date_added"}}],"next_cursor":...,"total_count":...}`.
You can also filter by company `company.basic_info.primary_domain`, or by title `job_details.title` with operator `(.)`.
An unsupported filter field returns 500 (not 400) with "Unsupported columns in conditions".

## /web/search/live
Request: `{"query":"\"Acme Leathers\" Kanpur fire","location":"IN","sources":["news","web"]}`. Optional `site`, `start_date`/`end_date` (unix seconds), `page` (page > 1 needs exactly one source).
Response: `{"success":true,"query":...,"timestamp":<ms>,"results":[{"source","title","url","snippet","position"}],"metadata":{...}}`.
**Results have NO date field.** Get the date from the article page (/web/enrich/live), or leave `dated` null.

## /web/enrich/live
Request: `{"urls":["https://..."]}` (1–10 URLs). Response is an array of `{success, url, timestamp, title, content}`. `content` is raw HTML. A failed fetch comes back with `success: false`.

## Watchers
Entity watch: `POST /watch/company` with
```json
{"entities":{"domains":["x.com"]},"track":{"field":"headcount.total","type":"changed"},
 "fields":["basic_info","headcount"],"config":{...},"notifications":[{"type":"webhook","url":"..."}]}
```
The webhook payload's `results` is a list of `{changes:[{field,type,value,from,to}], record}`. Plan A is a simulated webhook (POST the same payload to our own /webhook endpoint).

## OpenSanctions (optional)
POST https://api.opensanctions.org/match/default with header `Authorization: ApiKey <key>`:
```json
{"queries":{"q":{"schema":"Company","properties":{"name":["Acme Leathers"],"jurisdiction":["in"]}}}}
```
Response: `responses.q.results[] {id, caption, score, match, datasets, properties.topics}`. `match` is true when score ≥ threshold (default 0.7).

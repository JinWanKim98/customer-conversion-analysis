-- SQL sections used by the analysis notebook.
-- Each section is selected by filename; do not execute the whole file as one batch.

-- BEGIN FILE: 03_matched_session_population.sql
-- Compare definitions on exactly the same deduped event population.
-- Remove missing supplied IDs BEFORE reconstructing inactivity sessions here.
WITH eligible AS (
 SELECT * FROM candidate_events WHERE trim(user_id)<>'' AND trim(user_session)<>''
), gaps AS (
 SELECT *,ts-LAG(ts) OVER(PARTITION BY user_id ORDER BY ts,source_row) AS gap
 FROM eligible
), keys AS (
 SELECT *,
  SUM(gap IS NULL OR gap>1800) OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS s30,
  SUM(gap IS NULL OR gap>3600) OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS s60
 FROM gaps
), supplied AS (
 SELECT COUNT(*) AS n,SUM(event_type='purchase') AS p FROM eligible GROUP BY user_id,user_session
), s30 AS (
 SELECT COUNT(*) AS n,SUM(event_type='purchase') AS p FROM keys GROUP BY user_id,s30
), s60 AS (
 SELECT COUNT(*) AS n,SUM(event_type='purchase') AS p FROM keys GROUP BY user_id,s60
)
SELECT 'user_and_supplied_id' AS definition,COUNT(*) AS sessions,SUM(p>0) AS purchasing_sessions,
       SUM(n) AS eligible_events,SUM(p) AS purchase_events,
       100.0*SUM(p>0)/COUNT(*) AS diagnostic_purchase_rate_pct FROM supplied
UNION ALL
SELECT 'user_inactivity_30m',COUNT(*),SUM(p>0),SUM(n),SUM(p),100.0*SUM(p>0)/COUNT(*) FROM s30
UNION ALL
SELECT 'user_inactivity_60m',COUNT(*),SUM(p>0),SUM(n),SUM(p),100.0*SUM(p>0)/COUNT(*) FROM s60;

-- BEGIN FILE: 03_quality_checks.sql
-- name: duplicate_breakdown
SELECT event_type,COUNT(*) AS removed_rows
FROM ranked_events WHERE duplicate_rank>1 GROUP BY event_type ORDER BY event_type;

-- name: source_time_order
WITH ordered AS (
 SELECT ts,LAG(ts) OVER(ORDER BY source_row) AS previous_ts FROM raw_events
)
SELECT SUM(ts<previous_ts) AS decreasing_timestamp_rows,
       SUM(ts=previous_ts) AS same_second_adjacent_rows FROM ordered;

-- name: raw_monthly_missingness
SELECT substr(event_time,1,7) AS month,COUNT(*) AS events,
       SUM(trim(category_code)='') AS missing_category,
       SUM(trim(brand)='') AS missing_brand,
       SUM(trim(user_session)='') AS missing_session
FROM raw_events GROUP BY month ORDER BY month;

-- name: missing_session_events
SELECT event_type,COUNT(*) AS events,COUNT(DISTINCT user_id) AS users
FROM candidate_events WHERE trim(user_session)='' GROUP BY event_type ORDER BY event_type;

-- name: supplied_pair_duration_buckets
WITH spans AS (
 SELECT user_id,user_session,MAX(ts)-MIN(ts) AS seconds
 FROM candidate_events WHERE trim(user_id)<>'' AND trim(user_session)<>''
 GROUP BY user_id,user_session
)
SELECT CASE WHEN seconds=0 THEN '0: single timestamp'
            WHEN seconds<=1800 THEN '1: 0-30 minutes'
            WHEN seconds<=3600 THEN '2: 30-60 minutes'
            WHEN seconds<=86400 THEN '3: 1-24 hours'
            ELSE '4: over 24 hours' END AS duration_bucket,
       COUNT(*) AS pairs,MAX(seconds) AS max_seconds
FROM spans GROUP BY duration_bucket ORDER BY duration_bucket;

-- name: session_id_collisions
WITH ids AS (
 SELECT user_session,COUNT(DISTINCT user_id) AS users,COUNT(*) AS events,
        SUM(event_type='purchase') AS purchase_events
 FROM candidate_events WHERE trim(user_session)<>'' AND trim(user_id)<>''
 GROUP BY user_session
)
SELECT COUNT(*) AS shared_session_ids,SUM(users) AS affected_user_session_pairs,
       SUM(events) AS affected_events,SUM(purchase_events) AS affected_purchase_events
FROM ids WHERE users>1;

-- name: category_mapping
WITH mapping AS (
 SELECT category_id,COUNT(DISTINCT CASE WHEN trim(category_code)<>'' THEN category_code END) AS codes,
        SUM(trim(category_code)='') AS missing_rows
 FROM candidate_events GROUP BY category_id
)
SELECT COUNT(*) AS category_ids,SUM(codes=0) AS no_observed_code_ids,
       SUM(codes=1) AS uniquely_mapped_ids,SUM(codes>1) AS ambiguous_mapping_ids,
       SUM(CASE WHEN codes=1 THEN missing_rows ELSE 0 END) AS potentially_recoverable_missing_rows,
       SUM(CASE WHEN codes=0 THEN missing_rows ELSE 0 END) AS missing_rows_without_mapping,
       SUM(CASE WHEN codes>1 THEN missing_rows ELSE 0 END) AS missing_rows_with_ambiguous_mapping
FROM mapping;

-- name: product_attribute_mapping
WITH mapping AS (
 SELECT product_id,COUNT(DISTINCT category_id) AS category_ids,
        COUNT(DISTINCT CASE WHEN trim(brand)<>'' THEN brand END) AS brands,
        SUM(trim(brand)='') AS missing_brand_rows
 FROM candidate_events GROUP BY product_id
)
SELECT COUNT(*) AS products,SUM(category_ids>1) AS products_with_multiple_category_ids,
       SUM(brands>1) AS products_with_multiple_observed_brands,
       SUM(CASE WHEN brands=1 THEN missing_brand_rows ELSE 0 END) AS potentially_recoverable_brand_rows
FROM mapping;

-- name: same_second_product_events
WITH ties AS (
 SELECT user_id,user_session,product_id,ts,COUNT(*) AS n,COUNT(DISTINCT event_type) AS kinds
 FROM candidate_events WHERE trim(user_session)<>''
 GROUP BY user_id,user_session,product_id,ts HAVING COUNT(*)>1
)
SELECT COUNT(*) AS tied_groups,COALESCE(SUM(n),0) AS tied_events,
       COALESCE(SUM(kinds>1),0) AS mixed_event_type_tied_groups FROM ties;

-- name: supplied_pair_purchase_antecedents
-- Strictly earlier timestamp, same observed user + supplied session + product.
-- RANGE ending 1 second earlier excludes all simultaneous events, regardless of CSV order.
WITH prior AS (
 SELECT *,
  MAX(CASE WHEN event_type='view' THEN ts END) OVER(
    PARTITION BY user_id,user_session,product_id ORDER BY ts
    RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_view_ts,
  MAX(CASE WHEN event_type='cart' THEN ts END) OVER(
    PARTITION BY user_id,user_session,product_id ORDER BY ts
    RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_cart_ts,
  MAX(event_type='view') OVER(PARTITION BY user_id,user_session,product_id,ts) AS simultaneous_view,
  MAX(event_type='cart') OVER(PARTITION BY user_id,user_session,product_id,ts) AS simultaneous_cart
 FROM candidate_events WHERE trim(user_id)<>'' AND trim(user_session)<>''
)
SELECT COUNT(*) AS purchase_events,SUM(prior_view_ts IS NULL) AS without_strictly_prior_view,
       SUM(prior_cart_ts IS NULL) AS without_strictly_prior_cart,
       SUM(prior_view_ts IS NULL AND simultaneous_view=1) AS prior_view_absent_but_same_second_view,
       SUM(prior_cart_ts IS NULL AND simultaneous_cart=1) AS prior_cart_absent_but_same_second_cart
FROM prior WHERE event_type='purchase';

-- name: reconstructed_30m_purchase_antecedents
WITH prior AS (
 SELECT *,
  MAX(CASE WHEN event_type='view' THEN ts END) OVER(
    PARTITION BY user_id,session_30,product_id ORDER BY ts
    RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_view_ts,
  MAX(CASE WHEN event_type='cart' THEN ts END) OVER(
    PARTITION BY user_id,session_30,product_id ORDER BY ts
    RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_cart_ts
 FROM qa_events WHERE session_30 IS NOT NULL
)
SELECT COUNT(*) AS purchase_events,SUM(prior_view_ts IS NULL) AS without_strictly_prior_view,
       SUM(prior_cart_ts IS NULL) AS without_strictly_prior_cart
FROM prior WHERE event_type='purchase';

-- name: window_edges
WITH bounds AS (SELECT MIN(ts) AS first_ts,MAX(ts) AS last_ts FROM candidate_events)
SELECT COUNT(*) AS events,SUM(ts<first_ts+86400) AS first_24h_events,
       SUM(ts>last_ts-86400) AS last_24h_events,
       COUNT(DISTINCT CASE WHEN ts>last_ts-7*86400 THEN user_id END) AS users_observed_in_last_7d,
       SUM(event_type='purchase' AND ts<first_ts+86400) AS first_24h_purchase_events,
       SUM(event_type='purchase' AND ts>last_ts-86400) AS last_24h_purchase_events
FROM candidate_events CROSS JOIN bounds;

-- name: observation_months
SELECT substr(event_time,1,7) AS month,COUNT(*) AS events,
       COUNT(DISTINCT substr(event_time,1,10)) AS observed_utc_dates,
       MIN(event_time) AS first_event,MAX(event_time) AS last_event
FROM candidate_events GROUP BY month ORDER BY month;

-- BEGIN FILE: 03_quality_models.sql
-- QA candidate models only. These are not the final Chapter 05 curated model.
-- Raw CSV values are preserved as TEXT; comparisons use exact original fields.
CREATE TABLE ranked_events AS
SELECT *, ROW_NUMBER() OVER (
    PARTITION BY event_time,event_type,product_id,category_id,category_code,
                 brand,price,user_id,user_session
    ORDER BY source_row
) AS duplicate_rank
FROM raw_events;

CREATE TABLE candidate_events AS
SELECT * FROM ranked_events WHERE duplicate_rank=1;
CREATE INDEX candidate_user_time ON candidate_events(user_id,ts,source_row);
CREATE INDEX candidate_pair_product_time ON candidate_events(user_id,user_session,product_id,ts);

-- Reconstruct inactivity sessions independently of the supplied session IDs.
-- 30 and 60 minutes are sensitivity choices, not claims about provider semantics.
-- A gap EXACTLY equal to the threshold stays in the current session.
-- Same-second ties use source row for deterministic assignment, not causal order.
CREATE TABLE session_gaps AS
SELECT source_row,user_id,ts,
       ts-LAG(ts) OVER(PARTITION BY user_id ORDER BY ts,source_row) AS gap_seconds
FROM candidate_events
WHERE trim(user_id)<>'' AND ts IS NOT NULL;

CREATE TABLE candidate_session_keys AS
SELECT source_row,user_id,
       SUM(CASE WHEN gap_seconds IS NULL OR gap_seconds>1800 THEN 1 ELSE 0 END)
          OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS session_30,
       SUM(CASE WHEN gap_seconds IS NULL OR gap_seconds>3600 THEN 1 ELSE 0 END)
          OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS session_60
FROM session_gaps;
CREATE UNIQUE INDEX candidate_key_row ON candidate_session_keys(source_row);

CREATE VIEW qa_events AS
SELECT e.*,k.session_30,k.session_60
FROM candidate_events e LEFT JOIN candidate_session_keys k USING(source_row);

-- BEGIN FILE: 04_reference_metrics.sql
-- Synthetic reference implementation of the Chapter 04 contract.
-- Input canonical_events is ALREADY exact-deduped and validated.
-- Parameters are bound from docs/04_metric_contract.json, not interpolated.
WITH gaps AS (
 SELECT *,ts-LAG(ts) OVER(PARTITION BY user_id ORDER BY ts,source_row) AS gap
 FROM canonical_events
), events AS (
 SELECT *,SUM(gap IS NULL OR gap>:gap_seconds)
   OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS session_id
 FROM gaps
), session_groups AS (
 SELECT user_id,session_id,MAX(ts) AS last_ts,MAX(event_type='purchase') AS purchased
 FROM events GROUP BY user_id,session_id
), pairs AS (
 SELECT user_id,product_id,
  MIN(CASE WHEN event_type='view' THEN ts END) AS view_anchor,
  MIN(CASE WHEN event_type='cart' THEN ts END) AS cart_anchor
 FROM events GROUP BY user_id,product_id
), views AS (
 SELECT p.*,(SELECT MIN(e.ts) FROM events e WHERE e.user_id=p.user_id AND e.product_id=p.product_id
    AND e.event_type='cart' AND e.ts>p.view_anchor AND e.ts<=p.view_anchor+:horizon_seconds) AS cart_ts
 FROM pairs p WHERE view_anchor<=:observed_end-:horizon_seconds
), view_chain AS (
 SELECT v.*,EXISTS(SELECT 1 FROM events e WHERE e.user_id=v.user_id AND e.product_id=v.product_id
  AND e.event_type='purchase' AND e.ts>v.cart_ts AND e.ts<=v.view_anchor+:horizon_seconds) AS bought
 FROM views v
), carts AS (
 SELECT p.*,EXISTS(SELECT 1 FROM events e WHERE e.user_id=p.user_id AND e.product_id=p.product_id
   AND e.event_type='purchase' AND e.ts>p.cart_anchor AND e.ts<=p.cart_anchor+:horizon_seconds) AS bought
 FROM pairs p WHERE cart_anchor<=:observed_end-:horizon_seconds
), sp AS (
 SELECT e.user_id,e.session_id,e.product_id,MIN(e.ts) AS view_anchor
 FROM events e JOIN session_groups s ON e.user_id=s.user_id AND e.session_id=s.session_id
 WHERE e.event_type='view' AND s.last_ts+:gap_seconds<=:observed_end
 GROUP BY e.user_id,e.session_id,e.product_id
), sp_cart AS (
 SELECT s.*,(SELECT MIN(e.ts) FROM events e WHERE e.user_id=s.user_id
  AND e.session_id=s.session_id AND e.product_id=s.product_id
  AND e.event_type='cart' AND e.ts>s.view_anchor) AS cart_ts
 FROM sp s
), sp_chain AS (
 SELECT s.*,EXISTS(SELECT 1 FROM events e WHERE e.user_id=s.user_id
  AND e.session_id=s.session_id AND e.product_id=s.product_id
  AND e.event_type='purchase' AND e.ts>s.cart_ts) AS bought FROM sp_cart s
)
SELECT
 (SELECT COUNT(DISTINCT user_id) FROM events) AS user_den,
 (SELECT COUNT(DISTINCT user_id) FROM events WHERE event_type='purchase') AS user_num,
 (SELECT COUNT(*) FROM session_groups) AS session_den,
 (SELECT COUNT(*) FROM session_groups WHERE purchased=1) AS session_num,
 (SELECT COUNT(*) FROM views) AS view7_den,
 (SELECT COUNT(*) FROM view_chain WHERE cart_ts IS NOT NULL) AS view_cart7_num,
 (SELECT COUNT(*) FROM view_chain WHERE bought=1) AS view_cart_purchase7_num,
 (SELECT COUNT(*) FROM carts) AS cart7_den,
 (SELECT COUNT(*) FROM carts WHERE bought=1) AS cart_purchase7_num,
 (SELECT COUNT(*) FROM sp_chain) AS session_product_den,
 (SELECT COUNT(*) FROM sp_chain WHERE cart_ts IS NOT NULL) AS session_product_cart_num,
 (SELECT COUNT(*) FROM sp_chain WHERE bought=1) AS session_product_purchase_num,
 (SELECT COUNT(*) FROM pairs WHERE view_anchor>:observed_end-:horizon_seconds) AS excluded_late_view_anchors,
 (SELECT COUNT(*) FROM pairs WHERE cart_anchor>:observed_end-:horizon_seconds) AS excluded_late_cart_anchors,
 (SELECT COUNT(*) FROM session_groups WHERE last_ts+:gap_seconds>:observed_end) AS excluded_open_session_groups;

-- BEGIN FILE: 05_build_model.sql
-- Production REES46 model. Config is bound once in model_config by Python.
-- Raw original nine-field equality controls duplicate identity; no attribute fill.

-- stage: lineage and events
CREATE TABLE _lineage AS
SELECT source_row,MIN(source_row) OVER (
 PARTITION BY event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session
) AS canonical_source_row FROM staging_events;
CREATE UNIQUE INDEX lineage_row ON _lineage(source_row);

CREATE TABLE dim_user(user_id TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE dim_product(product_id TEXT PRIMARY KEY) WITHOUT ROWID;
INSERT INTO dim_user SELECT DISTINCT user_id FROM staging_events;
INSERT INTO dim_product SELECT DISTINCT product_id FROM staging_events;

CREATE TABLE fact_event(
 source_row INTEGER PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES dim_user(user_id),
 product_id TEXT NOT NULL REFERENCES dim_product(product_id),
 event_time TEXT NOT NULL,ts INTEGER NOT NULL,
 event_type TEXT NOT NULL CHECK(event_type IN ('view','cart','purchase')),
 category_id TEXT NOT NULL,category_code TEXT NOT NULL,brand TEXT NOT NULL,
 price_raw TEXT NOT NULL,price_value REAL NOT NULL,user_session TEXT NOT NULL,
 UNIQUE(source_row,user_id)
);
INSERT INTO fact_event
SELECT s.source_row,s.user_id,s.product_id,s.event_time,s.ts,s.event_type,
       s.category_id,s.category_code,s.brand,s.price,s.price_value,s.user_session
FROM staging_events s JOIN _lineage l USING(source_row)
WHERE s.source_row=l.canonical_source_row;
CREATE INDEX event_user_product_type_time ON fact_event(user_id,product_id,event_type,ts,source_row);
CREATE INDEX event_user_time ON fact_event(user_id,ts,source_row);

CREATE TABLE event_lineage(
 source_row INTEGER PRIMARY KEY,
 canonical_source_row INTEGER NOT NULL REFERENCES fact_event(source_row)
);
INSERT INTO event_lineage SELECT source_row,canonical_source_row FROM _lineage;
DROP TABLE _lineage;

-- stage: reconstructed sessions
CREATE TABLE _gaps AS
SELECT source_row,user_id,ts,ts-LAG(ts) OVER(PARTITION BY user_id ORDER BY ts,source_row) AS gap
FROM fact_event;
CREATE TABLE _session_keys AS
SELECT source_row,user_id,
 SUM(gap IS NULL OR gap>(SELECT gap_seconds FROM model_config))
   OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS session_30,
 SUM(gap IS NULL OR gap>(SELECT sensitivity_gap_seconds FROM model_config))
   OVER(PARTITION BY user_id ORDER BY ts,source_row ROWS UNBOUNDED PRECEDING) AS session_60
FROM _gaps;
CREATE UNIQUE INDEX session_keys_row ON _session_keys(source_row);
CREATE TABLE fact_session_30(
 user_id TEXT NOT NULL REFERENCES dim_user(user_id),session_id INTEGER NOT NULL,
 first_ts INTEGER NOT NULL,last_ts INTEGER NOT NULL,event_count INTEGER NOT NULL,
 purchase_events INTEGER NOT NULL,closed_in_snapshot INTEGER NOT NULL CHECK(closed_in_snapshot IN (0,1)),
 PRIMARY KEY(user_id,session_id)
) WITHOUT ROWID;
INSERT INTO fact_session_30
SELECT e.user_id,k.session_30,MIN(e.ts),MAX(e.ts),COUNT(*),SUM(e.event_type='purchase'),
 MAX(e.ts)+(SELECT gap_seconds FROM model_config)<=(SELECT observed_end FROM model_config)
FROM fact_event e JOIN _session_keys k USING(source_row) GROUP BY e.user_id,k.session_30;
CREATE TABLE fact_session_60(
 user_id TEXT NOT NULL REFERENCES dim_user(user_id),session_id INTEGER NOT NULL,
 first_ts INTEGER NOT NULL,last_ts INTEGER NOT NULL,event_count INTEGER NOT NULL,
 purchase_events INTEGER NOT NULL,closed_in_snapshot INTEGER NOT NULL CHECK(closed_in_snapshot IN (0,1)),
 PRIMARY KEY(user_id,session_id)
) WITHOUT ROWID;
INSERT INTO fact_session_60
SELECT e.user_id,k.session_60,MIN(e.ts),MAX(e.ts),COUNT(*),SUM(e.event_type='purchase'),
 MAX(e.ts)+(SELECT sensitivity_gap_seconds FROM model_config)<=(SELECT observed_end FROM model_config)
FROM fact_event e JOIN _session_keys k USING(source_row) GROUP BY e.user_id,k.session_60;
CREATE TABLE bridge_event_session(
 source_row INTEGER PRIMARY KEY,user_id TEXT NOT NULL,session_30 INTEGER NOT NULL,session_60 INTEGER NOT NULL,
 FOREIGN KEY(source_row,user_id) REFERENCES fact_event(source_row,user_id),
 FOREIGN KEY(user_id,session_30) REFERENCES fact_session_30(user_id,session_id),
 FOREIGN KEY(user_id,session_60) REFERENCES fact_session_60(user_id,session_id)
);
INSERT INTO bridge_event_session SELECT * FROM _session_keys;
CREATE INDEX event_session_30 ON bridge_event_session(user_id,session_30,source_row);
DROP TABLE _gaps;
DROP TABLE _session_keys;

-- stage: user product journeys
CREATE TABLE _pair_anchors AS
SELECT user_id,product_id,
 MIN(CASE WHEN event_type='view' THEN ts END) AS view_ts,
 MIN(CASE WHEN event_type='cart' THEN ts END) AS cart_anchor_ts
FROM fact_event GROUP BY user_id,product_id;
CREATE UNIQUE INDEX pair_anchor_key ON _pair_anchors(user_id,product_id);
CREATE TABLE _pair_cart AS
SELECT a.user_id,a.product_id,a.view_ts,a.cart_anchor_ts,
 MIN(CASE WHEN e.event_type='cart' AND e.ts>a.view_ts
           AND e.ts<=a.view_ts+(SELECT horizon_seconds FROM model_config) THEN e.ts END) AS cart_after_view_ts
FROM _pair_anchors a JOIN fact_event e ON e.user_id=a.user_id AND e.product_id=a.product_id
GROUP BY a.user_id,a.product_id,a.view_ts,a.cart_anchor_ts;
CREATE UNIQUE INDEX pair_cart_key ON _pair_cart(user_id,product_id);
CREATE TABLE mart_user_product(
 user_id TEXT NOT NULL REFERENCES dim_user(user_id),product_id TEXT NOT NULL REFERENCES dim_product(product_id),
 view_ts INTEGER,cart_anchor_ts INTEGER,cart_after_view_ts INTEGER,
 purchase_after_view_cart_ts INTEGER,purchase_after_cart_ts INTEGER,
 view_window_eligible INTEGER NOT NULL,cart_window_eligible INTEGER NOT NULL,
 PRIMARY KEY(user_id,product_id)
) WITHOUT ROWID;
INSERT INTO mart_user_product
SELECT a.user_id,a.product_id,a.view_ts,a.cart_anchor_ts,a.cart_after_view_ts,
 MIN(CASE WHEN e.event_type='purchase' AND e.ts>a.cart_after_view_ts
           AND e.ts<=a.view_ts+(SELECT horizon_seconds FROM model_config) THEN e.ts END),
 MIN(CASE WHEN e.event_type='purchase' AND e.ts>a.cart_anchor_ts
           AND e.ts<=a.cart_anchor_ts+(SELECT horizon_seconds FROM model_config) THEN e.ts END),
 CASE WHEN a.view_ts+(SELECT horizon_seconds FROM model_config)<=(SELECT observed_end FROM model_config) THEN 1 ELSE 0 END,
 CASE WHEN a.cart_anchor_ts+(SELECT horizon_seconds FROM model_config)<=(SELECT observed_end FROM model_config) THEN 1 ELSE 0 END
FROM _pair_cart a JOIN fact_event e ON e.user_id=a.user_id AND e.product_id=a.product_id
GROUP BY a.user_id,a.product_id,a.view_ts,a.cart_anchor_ts,a.cart_after_view_ts;
DROP TABLE _pair_anchors;
DROP TABLE _pair_cart;

-- stage: within session product journeys
CREATE TABLE _sp_anchors AS
SELECT e.user_id,b.session_30 AS session_id,e.product_id,
 MIN(CASE WHEN e.event_type='view' THEN e.ts END) AS view_ts
FROM fact_event e JOIN bridge_event_session b USING(source_row)
GROUP BY e.user_id,b.session_30,e.product_id;
CREATE UNIQUE INDEX sp_anchor_key ON _sp_anchors(user_id,session_id,product_id);
CREATE TABLE _sp_cart AS
SELECT a.user_id,a.session_id,a.product_id,a.view_ts,
 MIN(CASE WHEN e.event_type='cart' AND e.ts>a.view_ts THEN e.ts END) AS cart_after_view_ts
FROM _sp_anchors a
JOIN bridge_event_session b ON b.user_id=a.user_id AND b.session_30=a.session_id
JOIN fact_event e ON e.source_row=b.source_row AND e.product_id=a.product_id
GROUP BY a.user_id,a.session_id,a.product_id,a.view_ts;
CREATE UNIQUE INDEX sp_cart_key ON _sp_cart(user_id,session_id,product_id);
CREATE TABLE mart_session_product(
 user_id TEXT NOT NULL,session_id INTEGER NOT NULL,product_id TEXT NOT NULL REFERENCES dim_product(product_id),
 view_ts INTEGER,cart_after_view_ts INTEGER,purchase_after_view_cart_ts INTEGER,
 session_closed INTEGER NOT NULL CHECK(session_closed IN (0,1)),
 PRIMARY KEY(user_id,session_id,product_id),
 FOREIGN KEY(user_id,session_id) REFERENCES fact_session_30(user_id,session_id)
) WITHOUT ROWID;
INSERT INTO mart_session_product
SELECT a.user_id,a.session_id,a.product_id,a.view_ts,a.cart_after_view_ts,
 MIN(CASE WHEN e.event_type='purchase' AND e.ts>a.cart_after_view_ts THEN e.ts END),s.closed_in_snapshot
FROM _sp_cart a
JOIN bridge_event_session b ON b.user_id=a.user_id AND b.session_30=a.session_id
JOIN fact_event e ON e.source_row=b.source_row AND e.product_id=a.product_id
JOIN fact_session_30 s ON s.user_id=a.user_id AND s.session_id=a.session_id
GROUP BY a.user_id,a.session_id,a.product_id,a.view_ts,a.cart_after_view_ts,s.closed_in_snapshot;
DROP TABLE _sp_anchors;
DROP TABLE _sp_cart;

-- stage: reporting views
CREATE VIEW event_reporting AS
SELECT e.*,b.session_30,b.session_60,
 CASE WHEN trim(e.brand)='' THEN 'Unknown' ELSE e.brand END AS brand_label,
 CASE WHEN trim(e.category_code)='' THEN 'Unknown' ELSE e.category_code END AS category_label
FROM fact_event e JOIN bridge_event_session b USING(source_row);
-- Staging is derived scratch data, not the preserved raw CSV.
DROP TABLE staging_events;

-- BEGIN FILE: 05_metric_queries.sql
-- All denominators/numerators implement docs/04_metric_contract.json v1.0.0.
SELECT
 (SELECT COUNT(*) FROM dim_user) AS user_den,
 (SELECT COUNT(DISTINCT user_id) FROM fact_event WHERE event_type='purchase') AS user_num,
 (SELECT COUNT(*) FROM fact_session_30) AS session_den,
 (SELECT COUNT(*) FROM fact_session_30 WHERE purchase_events>0) AS session_num,
 (SELECT COUNT(*) FROM mart_user_product WHERE view_window_eligible=1) AS view7_den,
 (SELECT COUNT(*) FROM mart_user_product WHERE view_window_eligible=1 AND cart_after_view_ts IS NOT NULL) AS view_cart7_num,
 (SELECT COUNT(*) FROM mart_user_product WHERE view_window_eligible=1 AND purchase_after_view_cart_ts IS NOT NULL) AS view_cart_purchase7_num,
 (SELECT COUNT(*) FROM mart_user_product WHERE cart_window_eligible=1) AS cart7_den,
 (SELECT COUNT(*) FROM mart_user_product WHERE cart_window_eligible=1 AND purchase_after_cart_ts IS NOT NULL) AS cart_purchase7_num,
 (SELECT COUNT(*) FROM mart_session_product WHERE view_ts IS NOT NULL AND session_closed=1) AS session_product_den,
 (SELECT COUNT(*) FROM mart_session_product WHERE view_ts IS NOT NULL AND session_closed=1 AND cart_after_view_ts IS NOT NULL) AS session_product_cart_num,
 (SELECT COUNT(*) FROM mart_session_product WHERE view_ts IS NOT NULL AND session_closed=1 AND purchase_after_view_cart_ts IS NOT NULL) AS session_product_purchase_num,
 (SELECT COUNT(*) FROM mart_user_product WHERE view_ts IS NOT NULL AND view_window_eligible=0) AS excluded_late_view_anchors,
 (SELECT COUNT(*) FROM mart_user_product WHERE cart_anchor_ts IS NOT NULL AND cart_window_eligible=0) AS excluded_late_cart_anchors,
 (SELECT COUNT(*) FROM fact_session_30 WHERE closed_in_snapshot=0) AS excluded_open_session_groups;

-- BEGIN FILE: 06_eda_queries.sql
-- Descriptive profiles of the fixed Chapter 05 model. Not ordered funnel rates.

-- name: event_mix
SELECT event_type,COUNT(*) AS events,COUNT(DISTINCT user_id) AS users_with_event
FROM fact_event GROUP BY event_type ORDER BY event_type;

-- name: daily_utc
SELECT strftime('%Y-%m-%d',ts,'unixepoch') AS utc_date,COUNT(*) AS events,
 SUM(event_type='view') AS views,SUM(event_type='cart') AS carts,
 SUM(event_type='purchase') AS purchase_events
FROM fact_event GROUP BY utc_date ORDER BY utc_date;

-- name: monthly_utc
SELECT strftime('%Y-%m',ts,'unixepoch') AS month,COUNT(*) AS events,
 COUNT(DISTINCT strftime('%Y-%m-%d',ts,'unixepoch')) AS represented_dates,
 COUNT(DISTINCT user_id) AS observed_users,
 SUM(event_type='purchase') AS purchase_events
FROM fact_event GROUP BY month ORDER BY month;

-- name: hourly_utc
SELECT CAST(strftime('%H',ts,'unixepoch') AS INTEGER) AS utc_hour,
 COUNT(*) AS events,SUM(event_type='purchase') AS purchase_events
FROM fact_event GROUP BY utc_hour ORDER BY utc_hour;

-- name: user_event_frequency
WITH users AS (SELECT user_id,COUNT(*) AS events FROM fact_event GROUP BY user_id)
SELECT CASE WHEN events=1 THEN '1' WHEN events<=3 THEN '2-3'
 WHEN events<=9 THEN '4-9' ELSE '10+' END AS event_count_bucket,
 COUNT(*) AS users,SUM(events) AS events,MAX(events) AS max_user_events
FROM users GROUP BY event_count_bucket
ORDER BY CASE event_count_bucket WHEN '1' THEN 1 WHEN '2-3' THEN 2 WHEN '4-9' THEN 3 ELSE 4 END;

-- name: user_session_frequency
WITH users AS (SELECT user_id,COUNT(*) AS visits FROM fact_session_30 GROUP BY user_id)
SELECT CASE WHEN visits=1 THEN '1' WHEN visits=2 THEN '2'
 WHEN visits<=5 THEN '3-5' ELSE '6+' END AS observed_session_bucket,
 COUNT(*) AS users,SUM(visits) AS sessions
FROM users GROUP BY observed_session_bucket
ORDER BY CASE observed_session_bucket WHEN '1' THEN 1 WHEN '2' THEN 2 WHEN '3-5' THEN 3 ELSE 4 END;

-- name: session_event_frequency
SELECT CASE WHEN event_count=1 THEN '1' WHEN event_count<=3 THEN '2-3'
 WHEN event_count<=9 THEN '4-9' ELSE '10+' END AS event_count_bucket,
 COUNT(*) AS sessions,SUM(event_count) AS events,
 SUM(last_ts=first_ts) AS single_timestamp_sessions
FROM fact_session_30 GROUP BY event_count_bucket
ORDER BY CASE event_count_bucket WHEN '1' THEN 1 WHEN '2-3' THEN 2 WHEN '4-9' THEN 3 ELSE 4 END;

-- name: price_bands
SELECT CASE WHEN price_value<10 THEN '[0,10)' WHEN price_value<25 THEN '[10,25)'
 WHEN price_value<50 THEN '[25,50)' WHEN price_value<100 THEN '[50,100)'
 WHEN price_value<250 THEN '[100,250)' WHEN price_value<500 THEN '[250,500)'
 WHEN price_value<1000 THEN '[500,1000)' ELSE '[1000,+inf)' END AS price_band,
 COUNT(*) AS events,SUM(event_type='purchase') AS purchase_events,
 SUM(price_value=0) AS zero_price_events
FROM fact_event GROUP BY price_band
ORDER BY MIN(price_value);

-- name: category_profile
SELECT CASE WHEN trim(category_code)='' THEN 'Unknown' ELSE category_code END AS category_label,
 trim(category_code)='' AS category_missing,COUNT(*) AS events,
 SUM(event_type='view') AS views,SUM(event_type='cart') AS carts,
 SUM(event_type='purchase') AS purchase_events,COUNT(DISTINCT product_id) AS products
FROM fact_event GROUP BY category_label,category_missing ORDER BY events DESC,category_label;

-- name: attribute_missingness
SELECT COUNT(*) AS events,SUM(trim(category_code)='') AS missing_category_events,
 SUM(trim(brand)='') AS missing_brand_events,SUM(trim(user_session)='') AS missing_supplied_session_events
FROM fact_event;

-- name: product_event_distribution
SELECT events,COUNT(*) AS products
FROM (SELECT product_id,COUNT(*) AS events FROM fact_event GROUP BY product_id)
GROUP BY events ORDER BY events DESC;

-- name: observation_bounds
SELECT MIN(ts) AS first_ts,MAX(ts) AS last_ts,COUNT(*) AS events FROM fact_event;

-- BEGIN FILE: 07_conversion_diagnostics.sql
-- name: overall
SELECT cohort,COUNT(*) AS eligible_groups,SUM(cart_reached) AS cart_groups,
 SUM(ordered_purchase_reached) AS ordered_purchase_groups,
 COUNT(DISTINCT user_id) AS distinct_users,COUNT(DISTINCT product_id) AS distinct_products
FROM diagnostic_view_groups GROUP BY cohort ORDER BY cohort;

-- name: category
SELECT cohort,category_label,category_missing,COUNT(*) AS eligible_groups,
 SUM(cart_reached) AS cart_groups,SUM(ordered_purchase_reached) AS ordered_purchase_groups,
 COUNT(DISTINCT user_id) AS distinct_users,COUNT(DISTINCT product_id) AS distinct_products
FROM diagnostic_view_groups GROUP BY cohort,category_label,category_missing
ORDER BY cohort,eligible_groups DESC,category_label;

-- name: price_band
SELECT cohort,price_band,COUNT(*) AS eligible_groups,SUM(cart_reached) AS cart_groups,
 SUM(ordered_purchase_reached) AS ordered_purchase_groups,
 COUNT(DISTINCT user_id) AS distinct_users,COUNT(DISTINCT product_id) AS distinct_products
FROM diagnostic_view_groups GROUP BY cohort,price_band ORDER BY cohort,MIN(price_value);

-- name: exclusions
SELECT
 (SELECT COUNT(*) FROM mart_user_product WHERE view_ts IS NOT NULL AND view_window_eligible=0) AS late_view_pairs,
 (SELECT COUNT(*) FROM mart_user_product WHERE view_ts IS NULL) AS pairs_without_view,
 (SELECT COUNT(*) FROM mart_session_product WHERE view_ts IS NOT NULL AND session_closed=0) AS view_groups_in_open_sessions,
 (SELECT COUNT(*) FROM mart_session_product WHERE view_ts IS NULL) AS session_product_groups_without_view,
 (SELECT COUNT(*) FROM fact_session_30 WHERE closed_in_snapshot=0) AS open_sessions;

-- name: purchase_path_coverage
WITH purchase_groups AS (
 SELECT e.user_id,b.session_30 AS session_id,e.product_id,COUNT(*) AS purchase_events
 FROM fact_event e JOIN bridge_event_session b USING(source_row)
 WHERE e.event_type='purchase' GROUP BY e.user_id,b.session_30,e.product_id
), classified AS (
 SELECT p.purchase_events,
 CASE WHEN m.session_closed=0 THEN 'right_edge_session_excluded'
      WHEN m.view_ts IS NULL THEN 'no_observed_view_in_unit'
      WHEN m.cart_after_view_ts IS NULL THEN 'no_strict_cart_after_first_view'
      WHEN m.purchase_after_view_cart_ts IS NULL THEN 'no_strict_purchase_after_qualifying_cart'
      ELSE 'eligible_ordered_path' END AS path_status
 FROM purchase_groups p JOIN mart_session_product m USING(user_id,session_id,product_id)
)
SELECT path_status,COUNT(*) AS purchase_containing_groups,SUM(purchase_events) AS purchase_events
FROM classified GROUP BY path_status ORDER BY purchase_containing_groups DESC;

-- name: anchor_tie_audit
WITH versions AS (
 SELECT d.cohort,d.user_id,d.product_id,d.session_id,COUNT(*) AS views_at_anchor,
 COUNT(DISTINCT e.category_code)>1 OR COUNT(DISTINCT e.price_raw)>1 AS conflicting_attributes
 FROM diagnostic_view_groups d JOIN fact_event e ON e.user_id=d.user_id
  AND e.product_id=d.product_id AND e.event_type='view' AND e.ts=d.view_ts
 GROUP BY d.cohort,d.user_id,d.product_id,d.session_id
)
SELECT cohort,COUNT(*) AS eligible_groups,
 SUM(views_at_anchor>1) AS groups_with_multiple_view_records_at_anchor,
 SUM(conflicting_attributes) AS groups_with_conflicting_anchor_attributes
FROM versions GROUP BY cohort;

-- name: key_validation
SELECT
 (SELECT COUNT(*) FROM (
  SELECT cohort,user_id,product_id,session_id FROM diagnostic_view_groups
  GROUP BY cohort,user_id,product_id,session_id HAVING COUNT(*)<>1
 )) AS duplicate_group_keys,
 (SELECT COUNT(*) FROM diagnostic_view_groups
  WHERE ordered_purchase_reached>cart_reached) AS non_nested_purchase_groups;

-- BEGIN FILE: 07_diagnostic_cohorts.sql
-- Read-only persistent database; only TEMP scratch tables are created.
-- Attributes are from the first-view event, never future purchase events.
-- A source-row tie break selects attributes, not behavioral ordering.
CREATE TEMP TABLE diagnostic_view_groups AS
WITH entered AS (
 SELECT 'pair_7d' AS cohort,user_id,product_id,NULL AS session_id,view_ts,
        cart_after_view_ts IS NOT NULL AS cart_reached,
        purchase_after_view_cart_ts IS NOT NULL AS ordered_purchase_reached
 FROM mart_user_product WHERE view_window_eligible=1
 UNION ALL
 SELECT 'session_30',user_id,product_id,session_id,view_ts,
        cart_after_view_ts IS NOT NULL,purchase_after_view_cart_ts IS NOT NULL
 FROM mart_session_product WHERE view_ts IS NOT NULL AND session_closed=1
), anchored AS (
 SELECT m.*,a.source_row AS anchor_source_row,a.category_code,a.price_value
 FROM entered m JOIN fact_event a ON a.source_row=(
  SELECT MIN(e.source_row) FROM fact_event e
  WHERE e.user_id=m.user_id AND e.product_id=m.product_id
    AND e.event_type='view' AND e.ts=m.view_ts
 )
)
SELECT *,CASE WHEN trim(category_code)='' THEN 'Unknown' ELSE category_code END AS category_label,
 trim(category_code)='' AS category_missing,
 CASE WHEN price_value<10 THEN '[0,10)' WHEN price_value<25 THEN '[10,25)'
 WHEN price_value<50 THEN '[25,50)' WHEN price_value<100 THEN '[50,100)'
 WHEN price_value<250 THEN '[100,250)' WHEN price_value<500 THEN '[250,500)'
 WHEN price_value<1000 THEN '[500,1000)' ELSE '[1000,+inf)' END AS price_band
FROM anchored;
CREATE INDEX diagnostic_group_key ON diagnostic_view_groups(cohort,user_id,product_id,session_id);

-- BEGIN FILE: 08_robustness_setup.sql
-- Only temporary derived objects; persistent model is read-only.
CREATE TEMP TABLE robust_events60 AS
 SELECT e.source_row,e.user_id,e.product_id,e.ts,e.event_type,b.session_60 AS session_id
 FROM fact_event e JOIN bridge_event_session b USING(source_row);
CREATE INDEX robust60_lookup ON robust_events60(user_id,session_id,product_id,event_type,ts,source_row);
CREATE TEMP TABLE robust_sp60 AS
WITH anchors AS (
 SELECT e.user_id,e.session_id,e.product_id,MIN(e.ts) AS view_ts
 FROM robust_events60 e JOIN fact_session_60 s USING(user_id,session_id)
 WHERE e.event_type='view' AND s.closed_in_snapshot=1
 GROUP BY e.user_id,e.session_id,e.product_id
), carts AS (
 SELECT a.*,(SELECT MIN(e.ts) FROM robust_events60 e WHERE e.user_id=a.user_id
 AND e.session_id=a.session_id AND e.product_id=a.product_id AND e.event_type='cart'
 AND e.ts>a.view_ts) AS cart_ts FROM anchors a
), paths AS (
 SELECT a.*,(SELECT MIN(e.ts) FROM robust_events60 e WHERE e.user_id=a.user_id
 AND e.session_id=a.session_id AND e.product_id=a.product_id AND e.event_type='purchase'
 AND e.ts>a.cart_ts) AS purchase_ts FROM carts a
)
SELECT p.*,e.category_code,e.price_value FROM paths p JOIN fact_event e ON e.source_row=(
 SELECT MIN(v.source_row) FROM robust_events60 v WHERE v.user_id=p.user_id
 AND v.session_id=p.session_id AND v.product_id=p.product_id AND v.event_type='view' AND v.ts=p.view_ts);

CREATE TEMP TABLE robust_fixed_anchors AS
WITH selected AS (
 SELECT d.*,b.session_60 FROM diagnostic_view_groups d
 JOIN bridge_event_session b ON b.source_row=d.anchor_source_row
 JOIN fact_session_60 s ON s.user_id=b.user_id AND s.session_id=b.session_60
 WHERE d.cohort='session_30' AND s.closed_in_snapshot=1
), carts AS (
 SELECT a.*,(SELECT MIN(e.ts) FROM robust_events60 e WHERE e.user_id=a.user_id
 AND e.session_id=a.session_60 AND e.product_id=a.product_id AND e.event_type='cart'
 AND e.ts>a.view_ts) AS cart60_ts FROM selected a
)
SELECT a.*,(SELECT MIN(e.ts) FROM robust_events60 e WHERE e.user_id=a.user_id
 AND e.session_id=a.session_60 AND e.product_id=a.product_id AND e.event_type='purchase'
 AND e.ts>a.cart60_ts) AS purchase60_ts FROM carts a;

CREATE TEMP TABLE robust_windows AS
WITH windows(days) AS (VALUES(1),(3),(7)), populations(population) AS (VALUES('native'),('matched_7day'))
SELECT w.days,p.population,COUNT(*) AS eligible_groups,
 COALESCE(SUM(m.cart_after_view_ts<=m.view_ts+w.days*86400),0) AS cart_groups,
 COALESCE(SUM(m.purchase_after_view_cart_ts<=m.view_ts+w.days*86400),0) AS purchase_groups
FROM mart_user_product m CROSS JOIN windows w CROSS JOIN populations p
WHERE m.view_ts <= (SELECT observed_end FROM model_config)-
 CASE WHEN p.population='matched_7day' THEN 7 ELSE w.days END*86400
GROUP BY w.days,p.population;

CREATE TEMP TABLE robust_cart_windows AS
WITH windows(days) AS (VALUES(1),(3),(7)), populations(population) AS (VALUES('native'),('matched_7day'))
SELECT w.days,p.population,COUNT(*) AS eligible_groups,
 COALESCE(SUM(m.purchase_after_cart_ts<=m.cart_anchor_ts+w.days*86400),0) AS purchase_groups
FROM mart_user_product m CROSS JOIN windows w CROSS JOIN populations p
WHERE m.cart_anchor_ts <= (SELECT observed_end FROM model_config)-
 CASE WHEN p.population='matched_7day' THEN 7 ELSE w.days END*86400
GROUP BY w.days,p.population;

CREATE TEMP VIEW robust_segment_paths AS
SELECT 'native_30' AS scenario,user_id,product_id,category_code,price_value,
 cart_reached AS cart,ordered_purchase_reached AS purchase FROM diagnostic_view_groups WHERE cohort='session_30'
UNION ALL
SELECT 'native_60',user_id,product_id,category_code,price_value,cart_ts IS NOT NULL,purchase_ts IS NOT NULL FROM robust_sp60
UNION ALL
SELECT 'fixed_anchor_30',user_id,product_id,category_code,price_value,cart_reached,ordered_purchase_reached FROM robust_fixed_anchors
UNION ALL
SELECT 'fixed_anchor_60',user_id,product_id,category_code,price_value,cart60_ts IS NOT NULL,purchase60_ts IS NOT NULL FROM robust_fixed_anchors
UNION ALL
SELECT 'matched_window_'||w.days||'d',d.user_id,d.product_id,d.category_code,d.price_value,
 COALESCE(m.cart_after_view_ts<=m.view_ts+w.days*86400,0),
 COALESCE(m.purchase_after_view_cart_ts<=m.view_ts+w.days*86400,0)
FROM diagnostic_view_groups d JOIN mart_user_product m USING(user_id,product_id)
CROSS JOIN (SELECT 1 AS days UNION ALL SELECT 3 UNION ALL SELECT 7) w WHERE d.cohort='pair_7d';

-- BEGIN FILE: 09_hillstrom_summary.sql
-- Separate in-memory table. No REES46 tables/joins; preserve all assigned rows.
SELECT segment,COUNT(*) AS assigned_n,SUM(conversion) AS purchasers,SUM(visit) AS visitors,
 SUM(spend_cents) AS spend_cents_total,SUM(spend_cents=0) AS zero_spend_n,
 MAX(spend_cents) AS maximum_spend_cents
FROM assigned_customers GROUP BY segment ORDER BY segment;


-- SCRUM-254 — 시연 후보 경보 읽기 전용 내보내기(SELECT 만). 실행은 읽기 전용 트랜잭션으로(docs/str/08 "평가자 흔들림 — v4 초안").
-- 경보마다: 경보 원문·규칙·경보 거래 id·최신 점수 payload·prior(같은 법인 앞선 경보 수)·저장된 백엔드 요청 스냅샷(최신)·
-- SQL 판정 재료(facts 04 규칙 재현: self-transfer 제외·같은 법인 계좌 = 내부(법인 모르면 내부 아님)·상대 = 내부 뺀 입금·출금 상대).
-- psql 변수 ids = 쉼표로 나눈 경보 id(예 -v ids=7,48). 출력은 JSON 배열 한 줄 — `_tmp` 에만 저장(계좌 키 원본 포함, 커밋 안 함).
with pick as (
  select unnest(string_to_array(:'ids', ',')::bigint[]) aid
), k as (
  -- facts._is_internal 과 같게: 대상 법인 = 대상 계좌 행이 있으면 그 법인 칸(NULL 이어도 그대로), 행이 없을 때만 경보
  -- entity_id(TransactionReader.load_subject 와 같음, 추가 검토 2차). 내부 = S 가 낀 거래이고 상대 계좌 법인이
  -- 대상 법인과 같을 때만. 상대 계좌 행이 없거나 법인이 NULL 이면 내부 아님(coalesce false — NULL 이 NOT 필터로 빠지지 않게)
  select a.id aid, t.transaction_id, (t.from_account_key = a.account_key or t.to_account_key = a.account_key) involved,
         coalesce((t.from_account_key = a.account_key or t.to_account_key = a.account_key)
                  and (case when sa.account_key is null then a.entity_id else sa.entity_id end) is not null
                  and oa.entity_id = (case when sa.account_key is null then a.entity_id else sa.entity_id end), false) internal,
         t.from_account_key f, t.to_account_key tt, a.account_key s
  from ops.alerts a
  join pick on pick.aid = a.id
  join ops.alert_transactions x on x.alert_id = a.id
  join ops.transactions t on t.transaction_id = x.transaction_id
  left join ops.accounts sa on sa.account_key = a.account_key
  left join ops.accounts oa on oa.account_key = case when t.from_account_key = a.account_key then t.to_account_key
                                                     else t.from_account_key end
  where not t.is_self_transfer
), agg as (
  select aid,
         count(*) filter (where involved and not internal and tt = s) inbound,
         count(*) filter (where involved and not internal and f = s) outbound,
         count(*) filter (where internal) internal,
         count(distinct case when involved and not internal then (case when tt = s then f else tt end) end) counterparties
  from k group by aid
)
select coalesce(json_agg(json_build_object(
  'alert_id', a.id,
  'alert', json_build_object(
    'alert_no', a.alert_no, 'account_key', a.account_key, 'entity_id', a.entity_id,
    'window_start', to_char(a.window_start, 'YYYY-MM-DD"T"HH24:MI:SS'),
    'window_end', to_char(a.window_end, 'YYYY-MM-DD"T"HH24:MI:SS'),
    'reference_ts', to_char(a.reference_ts, 'YYYY-MM-DD"T"HH24:MI:SS'),
    'rule_facts', a.rule_facts,
    'created_at', to_char(a.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')),
  'rule', json_build_object('rule_id', r.rule_id, 'version', r.version, 'typology_hint', r.typology_hint),
  'tx_ids', (select json_agg(x.transaction_id order by x.transaction_id) from ops.alert_transactions x where x.alert_id = a.id),
  'score_payload', (select s.payload from ops.alert_scores s where s.alert_id = a.id order by s.produced_at desc limit 1),
  'prior_alert_count', (select count(*) from ops.alerts p
                        where a.entity_id is not null and p.entity_id = a.entity_id and p.reference_ts < a.reference_ts),
  'snapshot', (select d.request_snapshot from ops.str_draft_requests d join ops.cases c on c.id = d.case_id
               where c.alert_id = a.id order by d.created_at desc limit 1),
  'sql_counts', json_build_object('inbound', g.inbound, 'outbound', g.outbound, 'internal', g.internal,
                                  'counterparties', g.counterparties)
) order by a.id), '[]'::json)
from ops.alerts a
join pick on pick.aid = a.id
join ops.rules r on r.id = a.rule_ref_id
left join agg g on g.aid = a.id;

BEGIN;
LOCK TABLE ai.model_versions IN SHARE ROW EXCLUSIVE MODE;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ai.model_versions
        WHERE model_version='xgb-medium-c2-31-w1-d4-dev130'
          AND serving_package_version='0.1.0rc2'
    ) OR EXISTS (
        SELECT 1 FROM ai.model_versions WHERE is_serving AND model_version NOT IN
            ('xgb-medium-c2-31-w1-d4-dev130', 'xgb-hi-medium-r04-event-c2-31-v1')
    ) THEN RAISE EXCEPTION 'Unexpected demo serving state'; END IF;
END $$;
UPDATE ai.model_versions SET is_serving=false WHERE model_version='xgb-hi-medium-r04-event-c2-31-v1';
UPDATE ai.model_versions SET is_serving=true WHERE model_version='xgb-medium-c2-31-w1-d4-dev130';
COMMIT;

BEGIN;
LOCK TABLE ai.model_versions IN SHARE ROW EXCLUSIVE MODE;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ai.model_versions
        WHERE model_version = 'xgb-medium-c2-31-w1-d4-dev130'
          AND serving_package_version = '0.1.0rc2'
    ) OR EXISTS (
        SELECT 1 FROM ai.model_versions WHERE is_serving AND model_version NOT IN
            ('xgb-medium-c2-31-w1-d4-dev130', 'xgb-hi-medium-r04-event-c2-31-v1')
    ) THEN RAISE EXCEPTION 'Unexpected demo serving state'; END IF;
    IF EXISTS (
        SELECT 1 FROM ai.model_versions
        WHERE model_version = 'xgb-hi-medium-r04-event-c2-31-v1'
          AND (feature_version <> 'hi-medium-evidence31-96h-r04-event-v1' OR threshold <> 0.5
            OR serving_package_version IS DISTINCT FROM '0.1.0rc3'
            OR artifact_path <> '/models/r04_original.ubj')
    ) THEN RAISE EXCEPTION 'Unexpected rc3 metadata'; END IF;
END $$;
UPDATE ai.model_versions SET is_serving=false
WHERE model_version='xgb-medium-c2-31-w1-d4-dev130';
INSERT INTO ai.model_versions(model_version,feature_version,algorithm,threshold,artifact_path,
    serving_package_version,is_serving)
VALUES ('xgb-hi-medium-r04-event-c2-31-v1','hi-medium-evidence31-96h-r04-event-v1',
    'XGBoost',0.5,'/models/r04_original.ubj','0.1.0rc3',true)
ON CONFLICT (model_version) DO UPDATE SET is_serving=true;
COMMIT;

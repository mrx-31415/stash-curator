UPDATE curator_config
SET config_json=json_set(config_json, '$.moods', json_array(json_object(
    'id', 'together', 'name', 'Together',
    'excluded_tags', json(COALESCE(json_extract(config_json, '$.together_excluded_tags'), '[]'))
)))
WHERE json_type(config_json, '$.moods') IS NULL;

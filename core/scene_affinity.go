package main

import (
	"database/sql"
	"fmt"
	"math"
	"sort"
)

const sceneAffinityIDsQuery = `query CuratorSceneAffinityIds(
  $filter: FindFilterType, $scene_filter: SceneFilterType, $scene_ids: [Int!]
) {
  findScenes(filter: $filter, scene_filter: $scene_filter, scene_ids: $scene_ids) { scenes { id } }
}`
const sceneAffinityMetadataQuery = `query CuratorSceneAffinityMetadata(
  $filter: FindFilterType, $scene_filter: SceneFilterType, $scene_ids: [Int!]
) {
  findScenes(filter: $filter, scene_filter: $scene_filter, scene_ids: $scene_ids) { count duration filesize }
}`

type sceneAffinityScore struct {
	id                 string
	appeal, confidence sql.NullFloat64
}

func sceneAffinityRows(db dbx, modelID string, ids, args jVal) ([]sceneAffinityScore, error) {
	if ids.kind != jArr {
		return nil, fmt.Errorf("scene_ids must be a list of strings")
	}
	for _, id := range ids.arr {
		if id.kind != jStr || id.s == "" {
			return nil, fmt.Errorf("scene_ids must be a list of strings")
		}
	}
	criterion := args.get("criterion")
	modifier, threshold := "", float64(0)
	if criterion.kind != jNull {
		modifier = criterion.get("modifier").asString()
		switch modifier {
		case "GREATER_THAN", "LESS_THAN", "EQUALS", "NOT_EQUALS", "IS_NULL", "NOT_NULL":
		default:
			return nil, fmt.Errorf("unsupported Curator Appeal comparison")
		}
		if modifier != "IS_NULL" && modifier != "NOT_NULL" {
			value := criterion.get("value")
			number, err := pythonFloat(value)
			if value.kind != jNum || err != nil || math.IsNaN(number) || math.IsInf(number, 0) {
				return nil, fmt.Errorf("enter a valid Curator Appeal value")
			}
			threshold = number
		}
	}
	sorting := args.get("sort").truthy()
	direction := argsString(args, "direction", "DESC")
	if sorting {
		if direction != "ASC" && direction != "DESC" {
			return nil, fmt.Errorf("direction must be ASC or DESC")
		}
	}
	query := `SELECT i.value, s.appeal, s.confidence FROM json_each(?) i
LEFT JOIN model_scene_score s ON s.model_id=? AND s.scene_id=i.value`
	params := []any{ids.marshalCompact(), modelID}
	if sorting || criterion.kind != jNull {
		// One covering-index scan, then keyed lookups; SQLite may choose quadratic joins.
		query = `SELECT scene_id, appeal, confidence FROM model_scene_score WHERE model_id=?`
		params = []any{modelID}
	}
	rows, err := db.Query(query, params...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	scores := map[string]sceneAffinityScore{}
	for rows.Next() {
		var score sceneAffinityScore
		if err := rows.Scan(&score.id, &score.appeal, &score.confidence); err != nil {
			return nil, err
		}
		scores[score.id] = score
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	selected := []sceneAffinityScore{}
	for _, id := range ids.arr {
		score := scores[id.s]
		score.id = id.s
		known, value := score.appeal.Valid, score.appeal.Float64
		keep := modifier == ""
		switch modifier {
		case "IS_NULL":
			keep = !known
		case "NOT_NULL":
			keep = known
		case "GREATER_THAN":
			keep = known && value > threshold
		case "LESS_THAN":
			keep = known && value < threshold
		case "EQUALS":
			keep = known && value == threshold
		case "NOT_EQUALS":
			keep = known && value != threshold
		}
		if keep {
			selected = append(selected, score)
		}
	}
	if sorting {
		sort.SliceStable(selected, func(i, j int) bool {
			a, b := selected[i].appeal, selected[j].appeal
			if a.Valid != b.Valid {
				return a.Valid
			}
			if !a.Valid {
				return false
			}
			if direction == "ASC" {
				return a.Float64 < b.Float64
			}
			return a.Float64 > b.Float64
		})
	}
	return selected, nil
}

func opGetSceneAffinities(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, argsString(payload.get("args"), "operation", ""), func(settings jVal) (jVal, error) {
		args := payload.get("args")
		db, err := openAPISidecar(pluginDir, payload, settings)
		if err != nil {
			return jvNull(), err
		}
		defer db.Close()
		modelID, err := currentModelID(db)
		if err != nil {
			return jvNull(), err
		}
		if modelID == "" {
			return jvNull(), fmt.Errorf("no published model")
		}
		pageRequest := argsString(args, "operation", "") == "get_scene_affinity_page"
		ids := args.get("scene_ids")
		base, headers := stashConnection(payload)
		page, perPage := int64(1), int64(40)
		if args.has("page") {
			page = pythonInt(args.get("page"))
		}
		if args.has("per_page") {
			perPage = pythonInt(args.get("per_page"))
		}
		if pageRequest {
			if page < 1 || perPage < -1 {
				return jvNull(), fmt.Errorf("invalid scene page")
			}
			filter := args.get("filter")
			if filter.kind != jObj {
				filter = jvObj()
			}
			filter.set("page", jvInt(1))
			filter.set("per_page", jvInt(-1))
			data, err := graphqlQuery(base, headers, sceneAffinityIDsQuery, jvObj(
				jvKey("filter", filter), jvKey("scene_filter", args.get("scene_filter")), jvKey("scene_ids", ids)))
			if err != nil {
				return jvNull(), err
			}
			ids = jvArr()
			for _, scene := range data.get("findScenes").get("scenes").arr {
				ids.arr = append(ids.arr, scene.get("id"))
			}
		}
		rows, err := sceneAffinityRows(db, modelID, ids, args)
		if err != nil {
			return jvNull(), err
		}
		allIDs, pageIDs, affinities := jvArr(), jvArr(), jvObj()
		for _, score := range rows {
			id, appeal, confidence := score.id, score.appeal, score.confidence
			index := int64(len(allIDs.arr))
			allIDs.arr = append(allIDs.arr, jvStr(id))
			if pageRequest && perPage >= 0 && (index < (page-1)*perPage || index >= page*perPage) {
				continue
			}
			pageIDs.arr = append(pageIDs.arr, jvStr(id))
			if appeal.Valid {
				affinities.set(id, jvObj(jvKey("appeal", jvFloat(appeal.Float64)), jvKey("confidence", jvFloat(confidence.Float64))))
			}
		}
		result := jvObj(jvKey("schema_version", jvInt(apiSchemaVersion)), jvKey("model_id", jvStr(modelID)), jvKey("affinities", affinities))
		if pageRequest {
			metadata := jvObj(jvKey("count", jvInt(0)), jvKey("duration", jvFloat(0)), jvKey("filesize", jvFloat(0)))
			if len(allIDs.arr) > 0 {
				filter := args.get("filter")
				if filter.kind != jObj {
					filter = jvObj()
				}
				filter.set("per_page", jvInt(0))
				variables := jvObj(jvKey("filter", filter), jvKey("scene_filter", args.get("scene_filter")), jvKey("scene_ids", args.get("scene_ids")))
				if args.get("criterion").kind != jNull {
					numericIDs := jvArr()
					for _, id := range allIDs.arr {
						numericIDs.arr = append(numericIDs.arr, jvInt(pythonInt(id)))
					}
					variables = jvObj(jvKey("filter", jvObj(jvKey("per_page", jvInt(0)))), jvKey("scene_filter", jvNull()), jvKey("scene_ids", numericIDs))
				}
				data, err := graphqlQuery(base, headers, sceneAffinityMetadataQuery, variables)
				if err != nil {
					return jvNull(), err
				}
				metadata = data.get("findScenes")
			}
			result.set("scene_ids", pageIDs)
			result.set("count", metadata.get("count"))
			result.set("duration", metadata.get("duration"))
			result.set("filesize", metadata.get("filesize"))
		}
		return result, nil
	})
}

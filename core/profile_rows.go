package main

// Performer profile rows — the one read path behind every performer-profile
// loader (expand, targeted similar, local similar, the performer-similarity
// build stage). Schema-5 feature artifacts carry performer_profile: one
// compact JSON row per performer packing its profile:* features. Reading a
// few hundred rows instead of hundreds of thousands of entity_feature rows is
// what keeps Performer Hunt and Expand scoring fast; older artifacts fall back
// to the entity_feature join and yield the same values.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/buger/jsonparser"
)

// forEachProfileRow calls visit for every profile:* feature of the given
// performers (nil ids: every performer) in featureVersion, with the block
// name already stripped of its "profile:" prefix. Visit order within a
// performer is unspecified.
func forEachProfileRow(db dbx, featureVersion string, ids []string,
	visit func(performerID, block, name string, value, confidence float64)) error {
	packed, err := hasPerformerProfiles(db, featureVersion)
	if err != nil {
		return err
	}
	args := []any{featureVersion}
	filter := ""
	if ids != nil {
		if len(ids) == 0 {
			return nil
		}
		for _, id := range ids {
			args = append(args, id)
		}
	}
	if !packed {
		if ids != nil {
			filter = ` AND ef.entity_id IN (` + inClause(len(ids)) + `)`
		}
		rows, err := db.Query(`SELECT ef.entity_id, fd.family, fd.name, ef.value, ef.confidence
FROM entity_feature ef JOIN feature_definition fd USING(feature_id)
WHERE ef.feature_version=? AND ef.entity_type='performer' AND fd.family LIKE 'profile:%'`+filter+`
ORDER BY ef.entity_id, ef.feature_id`, args...)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var performerID, family, name string
			var value, confidence float64
			if err := rows.Scan(&performerID, &family, &name, &value, &confidence); err != nil {
				return err
			}
			visit(performerID, strings.TrimPrefix(family, "profile:"), name, value, confidence)
		}
		return rows.Err()
	}
	if ids != nil {
		filter = ` AND performer_id IN (` + inClause(len(ids)) + `)`
	}
	rows, err := db.Query(`SELECT performer_id, profile_json FROM performer_profile
WHERE feature_version=?`+filter+` ORDER BY performer_id`, args...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var performerID string
		var raw []byte
		if err := rows.Scan(&performerID, &raw); err != nil {
			return err
		}
		if err := visitPackedProfile(raw, func(block, name string, value, confidence float64) {
			visit(performerID, block, name, value, confidence)
		}); err != nil {
			return fmt.Errorf("invalid performer profile for %s: %w", performerID, err)
		}
	}
	return rows.Err()
}

// visitPackedProfile decodes one {block: {name: [value, confidence]}} row
// straight from the bytes: a generic JSON tree costs several times more on
// profiles with hundreds of entries.
func visitPackedProfile(raw []byte, visit func(block, name string, value, confidence float64)) error {
	return jsonparser.ObjectEach(raw, func(blockKey, blockValue []byte, kind jsonparser.ValueType, _ int) error {
		if kind != jsonparser.Object {
			return errors.New("profile block is not an object")
		}
		block, err := profileKey(blockKey)
		if err != nil {
			return err
		}
		return jsonparser.ObjectEach(blockValue, func(nameKey, pair []byte, kind jsonparser.ValueType, _ int) error {
			name, err := profileKey(nameKey)
			if err != nil {
				return err
			}
			var numbers [2]float64
			count := 0
			var itemErr error
			_, err = jsonparser.ArrayEach(pair, func(item []byte, kind jsonparser.ValueType, _ int, _ error) {
				if itemErr != nil {
					return
				}
				if kind != jsonparser.Number || count >= 2 {
					itemErr = errors.New("profile entry is not a [value, confidence] pair")
					return
				}
				numbers[count], itemErr = strconv.ParseFloat(string(item), 64)
				count++
			})
			if err == nil {
				err = itemErr
			}
			if err == nil && count != 2 {
				err = errors.New("profile entry is not a [value, confidence] pair")
			}
			if err != nil {
				return err
			}
			visit(block, name, numbers[0], numbers[1])
			return nil
		})
	})
}

// profileKey returns an object key's string value. The builder writes
// ensure_ascii JSON, so non-ASCII names arrive \u-escaped (surrogate pairs
// included); those rare keys go through encoding/json.
func profileKey(raw []byte) (string, error) {
	if bytes.IndexByte(raw, '\\') < 0 {
		return string(raw), nil
	}
	var key string
	err := json.Unmarshal(append(append([]byte{'"'}, raw...), '"'), &key)
	return key, err
}

// hasPerformerProfiles reports whether featureVersion's profiles are packed:
// performer_profile is readable (a temp view over an attached schema-5
// feature artifact, or a real table) and holds rows for that version. A
// schema that has the table but no packed rows reads entity_feature instead.
func hasPerformerProfiles(db dbx, featureVersion string) (bool, error) {
	var found int
	if err := db.QueryRow(`SELECT count(*) FROM (
  SELECT name FROM sqlite_temp_master WHERE name='performer_profile'
  UNION ALL SELECT name FROM sqlite_master WHERE name='performer_profile' AND type='table'
)`).Scan(&found); err != nil || found == 0 {
		return false, err
	}
	var packed bool
	err := db.QueryRow(`SELECT EXISTS(SELECT 1 FROM performer_profile WHERE feature_version=?)`,
		featureVersion).Scan(&packed)
	return packed, err
}

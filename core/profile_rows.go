package main

// Performer profile rows — the one read path behind every performer-profile
// loader (expand, targeted similar, local similar, the performer-similarity
// build stage). Newer feature artifacts carry performer_profile: one
// compact JSON row per performer packing its profile:* features. Reading a
// few hundred rows instead of hundreds of thousands of entity_feature rows is
// what keeps Performer Hunt and Expand scoring fast; older artifacts fall back
// to the entity_feature join and yield the same values.

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

// forEachProfileRow calls visit for every profile:* feature of the given
// performers (nil ids: every performer) in featureVersion, with the block
// name already stripped of its "profile:" prefix. name is only valid during
// the call, so a caller that keeps it copies it; most entries are compared
// and dropped. Visit order within a performer is unspecified.
func forEachProfileRow(db dbx, featureVersion string, ids []string,
	visit func(performerID, block string, name []byte, value, confidence float64)) error {
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
			visit(performerID, strings.TrimPrefix(family, "profile:"), []byte(name), value, confidence)
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
		var raw sql.RawBytes
		if err := rows.Scan(&performerID, &raw); err != nil {
			return err
		}
		if err := visitPackedProfile(raw, func(block string, name []byte, value, confidence float64) {
			visit(performerID, block, name, value, confidence)
		}); err != nil {
			return fmt.Errorf("invalid performer profile for %s: %w", performerID, err)
		}
	}
	return rows.Err()
}

// visitPackedProfile decodes one {block: {name: [value, confidence]}} row
// in a single pass over the bytes. Find, Expand and the model build read
// every performer's row, and a generic JSON walker (even a lazy one)
// rescans each value several times; this was most of performer Find.
func visitPackedProfile(raw []byte, visit func(block string, name []byte, value, confidence float64)) error {
	scan := packedProfileScanner{raw: raw}
	if !scan.expect('{') {
		return errors.New("profile is not an object")
	}
	for first := true; !scan.expect('}'); first = false {
		if !first && !scan.expect(',') {
			return errors.New("malformed profile object")
		}
		block, err := scan.key()
		if err != nil {
			return err
		}
		if !scan.expect('{') {
			return errors.New("profile block is not an object")
		}
		for first := true; !scan.expect('}'); first = false {
			if !first && !scan.expect(',') {
				return errors.New("malformed profile block")
			}
			name, err := scan.keyBytes()
			if err != nil {
				return err
			}
			value, valueOK := 0.0, scan.expect('[')
			confidence := 0.0
			if valueOK {
				value, valueOK = scan.number()
			}
			if valueOK {
				valueOK = scan.expect(',')
			}
			if valueOK {
				confidence, valueOK = scan.number()
			}
			if !valueOK || !scan.expect(']') {
				return errors.New("profile entry is not a [value, confidence] pair")
			}
			visit(block, name, value, confidence)
		}
	}
	scan.space()
	if scan.pos != len(raw) {
		return errors.New("trailing data after profile")
	}
	return nil
}

type packedProfileScanner struct {
	raw []byte
	pos int
}

func (s *packedProfileScanner) space() {
	for s.pos < len(s.raw) {
		switch s.raw[s.pos] {
		case ' ', '\t', '\n', '\r':
			s.pos++
		default:
			return
		}
	}
}

// expect consumes c (after whitespace) when it is next.
func (s *packedProfileScanner) expect(c byte) bool {
	s.space()
	if s.pos < len(s.raw) && s.raw[s.pos] == c {
		s.pos++
		return true
	}
	return false
}

// key reads a quoted object key and its colon.
func (s *packedProfileScanner) key() (string, error) {
	raw, err := s.keyBytes()
	return string(raw), err
}

// keyBytes is key without the copy: an unescaped key aliases raw.
func (s *packedProfileScanner) keyBytes() ([]byte, error) {
	if !s.expect('"') {
		return nil, errors.New("profile key is not a string")
	}
	start := s.pos
	for s.pos < len(s.raw) && s.raw[s.pos] != '"' {
		if s.raw[s.pos] == '\\' {
			s.pos++
		}
		s.pos++
	}
	if s.pos >= len(s.raw) {
		return nil, errors.New("unterminated profile key")
	}
	key := s.raw[start:s.pos]
	s.pos++
	if bytes.IndexByte(key, '\\') >= 0 {
		decoded, err := profileKey(key)
		if err != nil {
			return nil, err
		}
		key = []byte(decoded)
	}
	if !s.expect(':') {
		return nil, errors.New("profile key has no value")
	}
	return key, nil
}

// number reads a JSON number; NaN, Infinity and other tokens are rejected.
func (s *packedProfileScanner) number() (float64, bool) {
	s.space()
	start := s.pos
	for s.pos < len(s.raw) {
		c := s.raw[s.pos]
		if (c < '0' || c > '9') && c != '-' && c != '+' && c != '.' && c != 'e' && c != 'E' {
			break
		}
		s.pos++
	}
	if s.pos == start {
		return 0, false
	}
	value, err := strconv.ParseFloat(string(s.raw[start:s.pos]), 64)
	return value, err == nil
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
// performer_profile is readable (a temp view over an attached feature
// artifact, or a real table) and holds rows for that version. A
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

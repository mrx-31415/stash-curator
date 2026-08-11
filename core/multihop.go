// Personalized multi-hop affinity — a port of curator/model/multi_hop.py's
// MultiHopAffinity read path: load the persisted performer-collaboration
// graph, build the walkable subgraph seeded at a scene, and run the
// personalized PageRank in-process (the same pagerank kernel the Python side
// invokes through the binary's multi-hop stage).
package main

import (
	"database/sql"
	"sort"
)

const (
	multiHopDamping        = 0.85
	multiHopMaxIterations  = 100
	multiHopTolerance      = 1e-6
	multiHopTopK           = 50
	multiHopReachFloor     = 1e-6
	multiHopAffinityCutoff = 0.005
	multiHopStudioWeight   = 0.3
	multiHopTagWeight      = 0.15
)

// multiHop mirrors MultiHopAffinity's loaded state.
type multiHop struct {
	db              dbx
	modelID         string
	affinity        map[string]float64
	edges           map[string][]edgeEntry
	scenePerformers map[string][]string
	performerScenes map[string][]string
	sceneStudios    map[string]string
	sceneTags       map[string][]string
	loaded          bool
}

type edgeEntry struct {
	target     string
	similarity float64 // already cubed (similarity^3)
}

// newMultiHop mirrors MultiHopAffinity.__init__.
func newMultiHop(db dbx, modelID string) *multiHop {
	return &multiHop{
		db:              db,
		modelID:         modelID,
		affinity:        map[string]float64{},
		edges:           map[string][]edgeEntry{},
		scenePerformers: map[string][]string{},
		performerScenes: map[string][]string{},
		sceneStudios:    map[string]string{},
		sceneTags:       map[string][]string{},
	}
}

func (m *multiHop) load() error {
	if m.loaded {
		return nil
	}
	m.loaded = true
	rows, err := m.db.Query(`SELECT fd.name, fa.affinity, fa.confidence
FROM feature_affinity fa
JOIN feature_definition fd ON fd.feature_id = fa.feature_id
WHERE fa.model_id=? AND fd.family='performer_identity'
    AND fd.name LIKE 'performer:%'`, m.modelID)
	if err != nil {
		return err
	}
	for rows.Next() {
		var name string
		var affinity, confidence float64
		if err := rows.Scan(&name, &affinity, &confidence); err != nil {
			return err
		}
		effective := affinity * confidence
		if effective >= multiHopAffinityCutoff {
			m.affinity[trimPrefix(name, "performer:")] = effective
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	if len(m.affinity) == 0 {
		return nil
	}
	affinityKeys := sortedFloatKeysM(m.affinity)
	placeholders := inClause(len(affinityKeys))
	args := make([]any, 0, len(affinityKeys)+1)
	args = append(args, m.modelID)
	for _, key := range affinityKeys {
		args = append(args, key)
	}
	edgeRows, err := m.db.Query(`SELECT performer_id, similar_performer_id, similarity
FROM model_performer_edge
WHERE model_id=? AND performer_id IN (`+placeholders+`)
ORDER BY performer_id, rank`, args...)
	if err != nil {
		return err
	}
	for edgeRows.Next() {
		var performerID, similarID string
		var similarity float64
		if err := edgeRows.Scan(&performerID, &similarID, &similarity); err != nil {
			return err
		}
		m.edges[performerID] = append(m.edges[performerID], edgeEntry{target: similarID, similarity: (similarity * similarity * similarity)})
	}
	edgeRows.Close()
	if err := edgeRows.Err(); err != nil {
		return err
	}
	membership := make(map[string]map[string]bool)
	memberRows, err := m.db.Query(`SELECT scene_id, performer_id FROM scene_performer
WHERE performer_id IN (`+placeholders+`) ORDER BY scene_id, performer_id`, args...)
	if err != nil {
		return err
	}
	for memberRows.Next() {
		var sceneID, performerID string
		if err := memberRows.Scan(&sceneID, &performerID); err != nil {
			return err
		}
		set := membership[sceneID]
		if set == nil {
			set = map[string]bool{}
			membership[sceneID] = set
		}
		set[performerID] = true
	}
	memberRows.Close()
	if err := memberRows.Err(); err != nil {
		return err
	}
	for sceneID, set := range membership {
		ids := make([]string, 0, len(set))
		for id := range set {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		m.scenePerformers[sceneID] = ids
	}
	byPerformer := make(map[string]map[string]bool)
	for sceneID, performers := range m.scenePerformers {
		for _, performer := range performers {
			set := byPerformer[performer]
			if set == nil {
				set = map[string]bool{}
				byPerformer[performer] = set
			}
			set[sceneID] = true
		}
	}
	for performer, set := range byPerformer {
		ids := make([]string, 0, len(set))
		for id := range set {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		m.performerScenes[performer] = ids
	}
	walkable := make([]string, 0, len(m.scenePerformers))
	for sceneID := range m.scenePerformers {
		walkable = append(walkable, sceneID)
	}
	if len(walkable) == 0 {
		return nil
	}
	sort.Strings(walkable)
	scenePlaceholders := inClause(len(walkable))
	sceneArgs := make([]any, len(walkable))
	for i, sceneID := range walkable {
		sceneArgs[i] = sceneID
	}
	studioRows, err := m.db.Query(`SELECT scene_id, studio_id FROM source_scene
WHERE scene_id IN (`+scenePlaceholders+`) AND studio_id IS NOT NULL`, sceneArgs...)
	if err != nil {
		return err
	}
	for studioRows.Next() {
		var sceneID, studioID string
		if err := studioRows.Scan(&sceneID, &studioID); err != nil {
			return err
		}
		m.sceneStudios[sceneID] = studioID
	}
	studioRows.Close()
	if err := studioRows.Err(); err != nil {
		return err
	}
	tagSets := make(map[string]map[string]bool)
	tagRows, err := m.db.Query(`SELECT st.scene_id, st.tag_id FROM scene_tag st
WHERE st.scene_id IN (`+scenePlaceholders+`) ORDER BY st.scene_id, st.tag_id`, sceneArgs...)
	if err != nil {
		return err
	}
	for tagRows.Next() {
		var sceneID, tagID string
		if err := tagRows.Scan(&sceneID, &tagID); err != nil {
			return err
		}
		set := tagSets[sceneID]
		if set == nil {
			set = map[string]bool{}
			tagSets[sceneID] = set
		}
		set[tagID] = true
	}
	tagRows.Close()
	if err := tagRows.Err(); err != nil {
		return err
	}
	for sceneID, set := range tagSets {
		ids := make([]string, 0, len(set))
		for id := range set {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		m.sceneTags[sceneID] = ids
	}
	return nil
}

func trimPrefix(s, prefix string) string {
	if len(s) >= len(prefix) && s[:len(prefix)] == prefix {
		return s[len(prefix):]
	}
	return s
}

func sortedFloatKeysM(values map[string]float64) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// reach mirrors MultiHopAffinity.reach: personalized PageRank seeded at the
// scene, top scenes by (-score, scene), excluding the seed.
func (m *multiHop) reach(sceneID string) (map[string]float64, error) {
	if err := m.load(); err != nil {
		return nil, err
	}
	scores, err := m.walk(sceneID)
	if err != nil {
		return nil, err
	}
	ranked := make([]string, 0)
	for scene := range scores {
		if _, ok := m.scenePerformers[scene]; !ok {
			continue
		}
		if scene == sceneID {
			continue
		}
		if scores[scene] < multiHopReachFloor {
			continue
		}
		ranked = append(ranked, scene)
	}
	sort.Slice(ranked, func(i, j int) bool {
		if scores[ranked[i]] != scores[ranked[j]] {
			return scores[ranked[i]] > scores[ranked[j]]
		}
		return ranked[i] < ranked[j]
	})
	if len(ranked) > multiHopTopK {
		ranked = ranked[:multiHopTopK]
	}
	result := make(map[string]float64, len(ranked))
	for _, scene := range ranked {
		result[scene] = scores[scene]
	}
	return result, nil
}

// walk mirrors MultiHopAffinity._walk: build the seeded graph and run the
// power iteration.
func (m *multiHop) walk(seedID string) (map[string]float64, error) {
	if err := m.load(); err != nil {
		return nil, err
	}
	adjacency, seed, err := m.graphFor(seedID)
	if err != nil {
		return nil, err
	}
	if len(adjacency) < 2 {
		return map[string]float64{}, nil
	}
	return pagerank(adjacency, seed, multiHopDamping, multiHopMaxIterations, multiHopTolerance), nil
}

// graphFor mirrors MultiHopAffinity._graph_for: a scene seed builds the
// membership graph; a performer seed is walked the same way from its scenes.
func (m *multiHop) graphFor(seedID string) (map[string]map[string]float64, string, error) {
	if _, ok := m.scenePerformers[seedID]; ok {
		return m.graph(seedID), seedID, nil
	}
	weight, ok := m.affinity[seedID]
	if !ok {
		return map[string]map[string]float64{}, seedID, nil
	}
	adjacency := make(map[string]map[string]float64)
	for _, scene := range m.performerScenes[seedID] {
		setEdge(adjacency, seedID, scene, weight)
		setEdge(adjacency, scene, seedID, weight)
	}
	frontier := []string{seedID}
	seen := map[string]bool{seedID: true}
	for len(frontier) > 0 {
		performer := frontier[0]
		frontier = frontier[1:]
		for _, similar := range m.edges[performer] {
			setEdge(adjacency, performer, similar.target, similar.similarity)
			if seen[similar.target] {
				continue
			}
			seen[similar.target] = true
			w := m.affinity[similar.target]
			for _, scene := range m.performerScenes[similar.target] {
				setEdge(adjacency, similar.target, scene, w)
			}
			frontier = append(frontier, similar.target)
		}
	}
	return m.finalizeGraph(adjacency, seedID), seedID, nil
}

// graph mirrors MultiHopAffinity._graph for a scene seed.
func (m *multiHop) graph(seedScene string) map[string]map[string]float64 {
	adjacency := make(map[string]map[string]float64)
	seeds := m.scenePerformers[seedScene]
	for _, performer := range seeds {
		weight := m.affinity[performer]
		setEdge(adjacency, seedScene, performer, weight)
		setEdge(adjacency, performer, seedScene, weight)
	}
	frontier := make([]string, len(seeds))
	copy(frontier, seeds)
	seen := make(map[string]bool, len(seeds))
	for _, performer := range seeds {
		seen[performer] = true
	}
	for len(frontier) > 0 {
		performer := frontier[0]
		frontier = frontier[1:]
		for _, similar := range m.edges[performer] {
			setEdge(adjacency, performer, similar.target, similar.similarity)
			if seen[similar.target] {
				continue
			}
			seen[similar.target] = true
			weight := m.affinity[similar.target]
			for _, scene := range m.performerScenes[similar.target] {
				setEdge(adjacency, similar.target, scene, weight)
			}
			frontier = append(frontier, similar.target)
		}
	}
	return m.finalizeGraph(adjacency, seedScene)
}

// finalizeGraph mirrors MultiHopAffinity._finalize_graph: add studio and
// seed-tag bridges, ensure every target is a node, and row-normalize.
func (m *multiHop) finalizeGraph(adjacency map[string]map[string]float64, seedID string) map[string]map[string]float64 {
	for node := range adjacency {
		if _, ok := m.scenePerformers[node]; !ok {
			continue
		}
		if studio, ok := m.sceneStudios[node]; ok {
			studioNode := "studio:" + studio
			setEdge(adjacency, node, studioNode, multiHopStudioWeight)
			setEdge(adjacency, studioNode, node, multiHopStudioWeight)
		}
		if node != seedID {
			continue
		}
		for _, tagID := range m.sceneTags[node] {
			tagNode := "tag:" + tagID
			setEdge(adjacency, node, tagNode, multiHopTagWeight)
			setEdge(adjacency, tagNode, node, multiHopTagWeight)
		}
	}
	for _, edges := range adjacency {
		for target := range edges {
			if _, ok := adjacency[target]; !ok {
				adjacency[target] = map[string]float64{}
			}
		}
	}
	for node, edges := range adjacency {
		adjacency[node] = normalizeEdges(edges)
	}
	return adjacency
}

func setEdge(adjacency map[string]map[string]float64, from, to string, weight float64) {
	edges := adjacency[from]
	if edges == nil {
		edges = map[string]float64{}
		adjacency[from] = edges
	}
	edges[to] = weight
}

// normalizeEdges mirrors multi_hop._normalize: weights divided by their total
// over sorted edge pairs (the Python side sorts before summing, which fixes
// the float accumulation order).
func normalizeEdges(edges map[string]float64) map[string]float64 {
	keys := make([]string, 0, len(edges))
	for key := range edges {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	weights := make([]float64, 0, len(keys))
	for _, key := range keys {
		weights = append(weights, edges[key])
	}
	total := sumFloats(weights)
	if total <= 0 {
		return map[string]float64{}
	}
	result := make(map[string]float64, len(edges))
	for _, key := range keys {
		result[key] = edges[key] / total
	}
	return result
}

// multiHopVia mirrors similarity._multi_hop_via: a human-readable
// description of the strongest performer chain.
func (m *multiHop) multiHopVia(seedScene, candidateScene string) (string, error) {
	candidatePerformers := m.scenePerformers[candidateScene]
	if len(candidatePerformers) == 0 {
		return "", nil
	}
	seedPerformers := m.scenePerformers[seedScene]
	for _, sp := range seedPerformers {
		for _, cp := range candidatePerformers {
			for _, similar := range m.edges[sp] {
				if similar.target != cp {
					continue
				}
				spName, err := performerName(m.db, sp)
				if err != nil {
					return "", err
				}
				cpName, err := performerName(m.db, cp)
				if err != nil {
					return "", err
				}
				if spName != "" && cpName != "" && spName != cpName {
					return spName + " \u2248 " + cpName, nil
				}
				if spName != "" {
					return spName, nil
				}
			}
		}
	}
	return "shared tags", nil
}

// performerName mirrors similarity._performer_name.
func performerName(db dbx, performerID string) (string, error) {
	var name sql.NullString
	err := db.QueryRow(`SELECT name FROM source_performer WHERE performer_id=?`, performerID).Scan(&name)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	if name.Valid {
		return name.String, nil
	}
	return "", nil
}

// performerReach mirrors MultiHopAffinity.performer_reach: graph reach
// scores for specific performers, seeded at a scene or performer id,
// filtered to the reach floor.
func (m *multiHop) performerReach(seedID string, targetPerformerIDs map[string]bool) (map[string]float64, error) {
	if err := m.load(); err != nil {
		return nil, err
	}
	scores, err := m.walk(seedID)
	if err != nil {
		return nil, err
	}
	result := make(map[string]float64)
	for performerID := range targetPerformerIDs {
		score, ok := scores[performerID]
		if ok && score >= multiHopReachFloor {
			result[performerID] = score
		}
	}
	return result, nil
}

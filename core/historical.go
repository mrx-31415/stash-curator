// Historical preference-signal reconstruction — a port of
// curator/events/repository.py's HistoricalEventStore.rebuild plus the
// reconstruction math in curator/events/historical.py and the outcome curves
// in curator/events/curves.py. Rebuilds pseudo-sessions from source_play /
// source_o rows into play_session + behavior_event rows with
// provenance='historical_imputed'/'historical_import'.
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strings"
)

const (
	historicalViewConfidence = 0.45
	repeatBase               = 0.55
	repeatTauHours           = 6.0
	repeatConfidence         = 0.80
	oValue                   = 1.0
	oConfidence              = 1.0
	agreementConfidenceBonus = 0.05
	oMatchWindowHours        = 6.0
	shortExitSeconds         = 30.0
	viewRiseSeconds          = 90.0
	viewPositiveMax          = 0.35
	viewTailMin              = 0.05
	directShortExitMin       = -0.10
	directViewConfidence     = 0.80
)

// stableEventID mirrors historical.stable_event_id.
func stableEventID(kind, sceneID string, timestampMs int64, ordinal int64) string {
	raw := fmt.Sprintf("%s\x00%s\x00%d\x00%d", kind, sceneID, timestampMs, ordinal)
	digest := sha256.Sum256([]byte(raw))
	return fmt.Sprintf("historical-%s-%s", kind, hex.EncodeToString(digest[:])[:32])
}

type historicalPlay struct {
	playedAtMs int64
	ordinal    int64
}

type historicalO struct {
	occurredAtMs int64
	ordinal      int64
}

type normalizedOutcome struct {
	value             float64
	confidence        float64
	primarySignal     string
	observedAtMs      int64
	provenance        string
	supportingSignals []string
}

// oOutcome mirrors curves.o_outcome.
func oOutcome(observedAtMs int64) outcomeSignal {
	return outcomeSignal{"o", oValue, oConfidence, observedAtMs, "source_o_history"}
}

// repeatOutcome mirrors curves.repeat_outcome.
func repeatOutcome(gapHours float64, observedAtMs int64) (outcomeSignal, bool) {
	value := repeatBase * (1 - math.Exp(-gapHours/repeatTauHours))
	if value <= 0 {
		return outcomeSignal{}, false
	}
	return outcomeSignal{"repeat", value, repeatConfidence, observedAtMs, "source_play_history"}, true
}

// viewingOutcomeHistorical mirrors curves.viewing_outcome with
// historical_imputed=True: short sessions contribute no evidence.
func viewingOutcomeHistorical(activeSeconds float64, observedAtMs int64) (outcomeSignal, bool) {
	if !finite64(activeSeconds) || activeSeconds < 0 {
		return outcomeSignal{}, false
	}
	if activeSeconds < shortExitSeconds {
		return outcomeSignal{}, false
	}
	value := viewPositiveMax * (1 - math.Exp(-(activeSeconds-shortExitSeconds)/viewRiseSeconds))
	if mathAbs(value) < 1e-12 {
		return outcomeSignal{}, false
	}
	return outcomeSignal{"view", value, historicalViewConfidence, observedAtMs, "historical_imputed"}, true
}

// logOdds mirrors curves._log_odds.
func logOdds(curve [4]float64, seconds float64) float64 {
	logT := math.Log(seconds)
	return curve[0] + float64(curve[1]*logT) + float64(float64(curve[2]*logT)*logT)
}

// viewValueShipped is the two-piece shape used when nothing has been fitted.
func viewValueShipped(activeSeconds float64) float64 {
	if activeSeconds < shortExitSeconds {
		return directShortExitMin * (1 - activeSeconds/shortExitSeconds)
	}
	return viewPositiveMax * (1 - math.Exp(-(activeSeconds-shortExitSeconds)/viewRiseSeconds))
}

// viewValue mirrors curves.view_value. The bool reports whether there is any
// evidence at all: past the peak the fitted parabola keeps falling, but
// measured return rates out there are indistinguishable from the base rate, so
// the curve abstains rather than voting against.
func viewValue(activeSeconds float64, curve *[4]float64) (float64, bool) {
	if curve == nil {
		return viewValueShipped(activeSeconds), true
	}
	if activeSeconds <= 0.0 {
		// A zero duration means no duration was recorded, not that the scene
		// was watched for no time. See curves.view_value.
		return 0, false
	}
	curvature := curve[2]
	baseLogit := curve[3]
	if curvature >= 0.0 {
		return viewValueShipped(activeSeconds), true
	}
	peakSeconds := math.Exp(-curve[1] / (2.0 * curvature))
	span := logOdds(*curve, peakSeconds) - baseLogit
	if span < 1e-9 {
		return viewValueShipped(activeSeconds), true
	}
	relative := (logOdds(*curve, activeSeconds) - baseLogit) / span
	if activeSeconds > peakSeconds {
		// Soft clamp toward viewTailMin; see curves.view_value.
		decay := math.Exp(math.Min(relative, 1.0) - 1.0)
		return viewTailMin + (viewPositiveMax-viewTailMin)*decay, true
	}
	if relative >= 0.0 {
		return viewPositiveMax * math.Min(relative, 1.0), true
	}
	return directShortExitMin * math.Min(-relative, 1.0), true
}

// viewingOutcomeCurve mirrors curves.viewing_outcome.
func viewingOutcomeCurve(
	activeSeconds float64, observedAtMs int64, historicalImputed bool, curve *[4]float64,
) (outcomeSignal, bool) {
	if !finite64(activeSeconds) || activeSeconds < 0 {
		return outcomeSignal{}, false
	}
	if curve == nil && historicalImputed && activeSeconds < shortExitSeconds {
		return outcomeSignal{}, false
	}
	value, ok := viewValue(activeSeconds, curve)
	if !ok || mathAbs(value) < 1e-12 {
		return outcomeSignal{}, false
	}
	confidence := directViewConfidence
	provenance := "direct_player"
	if historicalImputed {
		confidence = historicalViewConfidence
		provenance = "historical_imputed"
	}
	return outcomeSignal{"view", value, confidence, observedAtMs, provenance}, true
}

// collapseSignals mirrors curves.collapse_signals.
func collapseSignals(signals []outcomeSignal) (normalizedOutcome, bool) {
	if len(signals) == 0 {
		return normalizedOutcome{}, false
	}
	primaryIndex := 0
	for i := 1; i < len(signals); i++ {
		if absF64(signals[i].value) > absF64(signals[primaryIndex].value) ||
			(absF64(signals[i].value) == absF64(signals[primaryIndex].value) &&
				signals[i].observedAtMs > signals[primaryIndex].observedAtMs) {
			primaryIndex = i
		}
	}
	primary := signals[primaryIndex]
	var supporting []string
	for i, item := range signals {
		if i != primaryIndex && item.value*primary.value > 0 {
			supporting = append(supporting, item.signalType)
		}
	}
	confidence := primary.confidence
	if len(supporting) > 0 {
		confidence = math.Min(1.0, confidence+agreementConfidenceBonus)
	}
	return normalizedOutcome{
		value:             primary.value,
		confidence:        confidence,
		primarySignal:     primary.signalType,
		observedAtMs:      primary.observedAtMs,
		provenance:        primary.provenance,
		supportingSignals: supporting,
	}, true
}

func absF64(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

// matchOs mirrors historical._match_os: greedily match plays and Os within
// the window by (distance, play index, o index).
func matchOs(plays []historicalPlay, os []historicalO, windowMs int64) (map[int]historicalO, map[int]bool) {
	type candidate struct {
		distance  int64
		playIndex int
		oIndex    int
	}
	var candidates []candidate
	for playIndex, play := range plays {
		for oIndex, outcome := range os {
			distance := abs64(play.playedAtMs - outcome.occurredAtMs)
			if distance <= windowMs {
				candidates = append(candidates, candidate{distance, playIndex, oIndex})
			}
		}
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		if a.distance != b.distance {
			return a.distance < b.distance
		}
		if a.playIndex != b.playIndex {
			return a.playIndex < b.playIndex
		}
		return a.oIndex < b.oIndex
	})
	matchedPlays := map[int]historicalO{}
	matchedOs := map[int]bool{}
	for _, c := range candidates {
		if _, taken := matchedPlays[c.playIndex]; taken {
			continue
		}
		if matchedOs[c.oIndex] {
			continue
		}
		matchedPlays[c.playIndex] = os[c.oIndex]
		matchedOs[c.oIndex] = true
	}
	return matchedPlays, matchedOs
}

func abs64(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

type reconstructedSession struct {
	sessionID   string
	sceneID     string
	startedAtMs int64
	endedAtMs   int64
	activeSecs  float64
	confidence  float64
	outcome     *normalizedOutcome
	matchedO    *historicalO
}

type standaloneOutcome struct {
	eventID string
	sceneID string
	outcome normalizedOutcome
}

// reconstructHistory mirrors historical.reconstruct_history.
func reconstructHistory(sceneID string, totalPlayDurationSeconds float64,
	plays []historicalPlay, os []historicalO) ([]reconstructedSession, []standaloneOutcome) {
	orderedPlays := append([]historicalPlay(nil), plays...)
	sort.SliceStable(orderedPlays, func(i, j int) bool {
		a, b := orderedPlays[i], orderedPlays[j]
		if a.playedAtMs != b.playedAtMs {
			return a.playedAtMs < b.playedAtMs
		}
		return a.ordinal < b.ordinal
	})
	orderedOs := append([]historicalO(nil), os...)
	sort.SliceStable(orderedOs, func(i, j int) bool {
		a, b := orderedOs[i], orderedOs[j]
		if a.occurredAtMs != b.occurredAtMs {
			return a.occurredAtMs < b.occurredAtMs
		}
		return a.ordinal < b.ordinal
	})
	averageSeconds := 0.0
	if len(orderedPlays) > 0 {
		averageSeconds = totalPlayDurationSeconds / float64(len(orderedPlays))
	}
	matched, matchedOs := matchOs(orderedPlays, orderedOs,
		int64(pyRound(oMatchWindowHours*3_600_000)))

	var sessions []reconstructedSession
	var previousTimestamp int64 = -1
	for index, play := range orderedPlays {
		var signals []outcomeSignal
		if view, ok := viewingOutcomeHistorical(averageSeconds, play.playedAtMs); ok {
			signals = append(signals, view)
		}
		if previousTimestamp >= 0 {
			if repeat, ok := repeatOutcome(float64(play.playedAtMs-previousTimestamp)/3_600_000, play.playedAtMs); ok {
				signals = append(signals, repeat)
			}
		}
		var matchedO *historicalO
		if m, ok := matched[index]; ok {
			matchedO = &m
			signals = append(signals, oOutcome(m.occurredAtMs))
		}
		var outcome *normalizedOutcome
		if collapsed, ok := collapseSignals(signals); ok {
			outcome = &collapsed
		}
		sessions = append(sessions, reconstructedSession{
			sessionID:   stableEventID("session", sceneID, play.playedAtMs, play.ordinal),
			sceneID:     sceneID,
			startedAtMs: play.playedAtMs,
			endedAtMs:   play.playedAtMs + int64(pyRound(averageSeconds*1000)),
			activeSecs:  averageSeconds,
			confidence:  historicalViewConfidence,
			outcome:     outcome,
			matchedO:    matchedO,
		})
		previousTimestamp = play.playedAtMs
	}
	var standalone []standaloneOutcome
	for index, outcome := range orderedOs {
		if matchedOs[index] {
			continue
		}
		normalized, ok := collapseSignals([]outcomeSignal{oOutcome(outcome.occurredAtMs)})
		if !ok {
			continue
		}
		standalone = append(standalone, standaloneOutcome{
			eventID: stableEventID("o", sceneID, outcome.occurredAtMs, outcome.ordinal),
			sceneID: sceneID,
			outcome: normalized,
		})
	}
	return sessions, standalone
}

type historicalBuildResult struct {
	sceneCount   int64
	sessionCount int64
	outcomeCount int64
}

// historicalRebuild mirrors HistoricalEventStore.rebuild.
func historicalRebuild(db dbx, sceneIDs []string, progress func(processed, total int)) (historicalBuildResult, error) {
	// _selection: nil -> no clause; empty -> WHERE 0; else WHERE col IN (...).
	clause := ""
	var args []any
	limited := sceneIDs != nil
	if limited && len(sceneIDs) == 0 {
		clause = "WHERE 0"
	} else if limited {
		placeholders := strings.TrimSuffix(strings.Repeat("?,", len(sceneIDs)), ",")
		clause = "WHERE scene_id IN (" + placeholders + ")"
		args = make([]any, len(sceneIDs))
		for i, id := range sceneIDs {
			args[i] = id
		}
	}
	type sceneRow struct {
		sceneID  string
		duration float64
	}
	var scenes []sceneRow
	rows, err := db.Query(`SELECT scene_id, play_duration_seconds FROM source_scene `+clause+` ORDER BY scene_id`, args...)
	if err != nil {
		return historicalBuildResult{}, err
	}
	for rows.Next() {
		var sceneID string
		var duration float64
		if err := rows.Scan(&sceneID, &duration); err != nil {
			rows.Close()
			return historicalBuildResult{}, err
		}
		scenes = append(scenes, sceneRow{sceneID, duration})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return historicalBuildResult{}, err
	}
	plays := map[string][]historicalPlay{}
	rows, err = db.Query(`SELECT scene_id, played_at_ms, ordinal FROM source_play `+clause+` ORDER BY scene_id, played_at_ms, ordinal`, args...)
	if err != nil {
		return historicalBuildResult{}, err
	}
	for rows.Next() {
		var sceneID string
		var playedAtMs, ordinal int64
		if err := rows.Scan(&sceneID, &playedAtMs, &ordinal); err != nil {
			rows.Close()
			return historicalBuildResult{}, err
		}
		plays[sceneID] = append(plays[sceneID], historicalPlay{playedAtMs, ordinal})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return historicalBuildResult{}, err
	}
	os := map[string][]historicalO{}
	rows, err = db.Query(`SELECT scene_id, occurred_at_ms, ordinal FROM source_o `+clause+` ORDER BY scene_id, occurred_at_ms, ordinal`, args...)
	if err != nil {
		return historicalBuildResult{}, err
	}
	for rows.Next() {
		var sceneID string
		var occurredAtMs, ordinal int64
		if err := rows.Scan(&sceneID, &occurredAtMs, &ordinal); err != nil {
			rows.Close()
			return historicalBuildResult{}, err
		}
		os[sceneID] = append(os[sceneID], historicalO{occurredAtMs, ordinal})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return historicalBuildResult{}, err
	}
	total := maxInt(1, len(scenes)*2)
	type reconstruction struct {
		sessions   []reconstructedSession
		standalone []standaloneOutcome
	}
	reconstructions := make([]reconstruction, len(scenes))
	for position, scene := range scenes {
		sessions, standalone := reconstructHistory(scene.sceneID, scene.duration,
			plays[scene.sceneID], os[scene.sceneID])
		reconstructions[position] = reconstruction{sessions, standalone}
		if progress != nil && (position+1 == len(scenes) || (position+1)%250 == 0) {
			progress(position+1, total)
		}
	}
	if err := withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, `DELETE FROM behavior_event WHERE provenance = 'historical_import'`+deleteSuffix(clause), args...); err != nil {
			return err
		}
		if _, err := conn.ExecContext(ctx, `DELETE FROM play_session WHERE provenance = 'historical_imputed'`+deleteSuffix(clause), args...); err != nil {
			return err
		}
		sessionCount := int64(0)
		outcomeCount := int64(0)
		for _, item := range reconstructions {
			for _, session := range item.sessions {
				summary := jvObj(
					jvKey("duration_basis", jvStr("scene_total_divided_by_play_timestamps")),
					jvKey("matched_o_at_ms", jvNull()),
				)
				if session.matchedO != nil {
					summary.set("matched_o_at_ms", jvInt(session.matchedO.occurredAtMs))
				}
				if _, err := conn.ExecContext(ctx, `
INSERT INTO play_session(
    session_id, scene_id, started_at_ms, ended_at_ms, active_seconds,
    provenance, confidence, summary_json
) VALUES (?, ?, ?, ?, ?, 'historical_imputed', ?, ?)`,
					session.sessionID, session.sceneID, session.startedAtMs, session.endedAtMs,
					session.activeSecs, session.confidence, summary.marshalSortedKeys()); err != nil {
					return err
				}
				sessionCount++
				if session.outcome != nil {
					if err := insertHistoricalOutcome(conn, session.sessionID+"-outcome",
						session.sceneID, *session.outcome, session.sessionID); err != nil {
						return err
					}
					outcomeCount++
				}
			}
			for _, standalone := range item.standalone {
				if err := insertHistoricalOutcome(conn, standalone.eventID,
					standalone.sceneID, standalone.outcome, ""); err != nil {
					return err
				}
				outcomeCount++
			}
		}
		return nil
	}); err != nil {
		return historicalBuildResult{}, err
	}
	// Phase-2 progress mirrors Python's insert loop positions (len(scenes)+1
	// onwards) and the empty-scene progress(1,1).
	if progress != nil && len(scenes) == 0 {
		progress(1, 1)
	}
	if progress != nil {
		for position := range reconstructions {
			pos := position + 1 + len(scenes)
			if pos == total || pos%250 == 0 {
				progress(pos, total)
			}
		}
	}
	sessionCount, outcomeCount := int64(0), int64(0)
	for _, item := range reconstructions {
		sessionCount += int64(len(item.sessions))
		for _, session := range item.sessions {
			if session.outcome != nil {
				outcomeCount++
			}
		}
		outcomeCount += int64(len(item.standalone))
	}
	return historicalBuildResult{
		sceneCount:   int64(len(scenes)),
		sessionCount: sessionCount,
		outcomeCount: outcomeCount,
	}, nil
}

// deleteSuffix mirrors repository._delete_projection's suffix construction.
func deleteSuffix(clause string) string {
	if clause == "" {
		return ""
	}
	return " AND " + strings.TrimPrefix(clause, "WHERE ")
}

// insertHistoricalOutcome mirrors repository._insert_outcome.
func insertHistoricalOutcome(conn *sql.Conn, eventID, sceneID string, outcome normalizedOutcome, sessionID string) error {
	supporting := jvArr()
	for _, signal := range outcome.supportingSignals {
		supporting.arr = append(supporting.arr, jvStr(signal))
	}
	payload := jvObj(
		jvKey("primary_signal", jvStr(outcome.primarySignal)),
		jvKey("primary_provenance", jvStr(outcome.provenance)),
		jvKey("supporting_signals", supporting),
	)
	var sessionArg any
	if sessionID != "" {
		sessionArg = sessionID
	}
	_, err := conn.ExecContext(context.Background(), `
INSERT INTO behavior_event(
    event_id, event_type, scene_id, occurred_at_ms, outcome, confidence,
    provenance, session_id, payload_json
) VALUES (?, 'occasion_outcome', ?, ?, ?, ?, 'historical_import', ?, ?)`,
		eventID, sceneID, outcome.observedAtMs, outcome.value, outcome.confidence,
		sessionArg, payload.marshalSortedKeys())
	return err
}

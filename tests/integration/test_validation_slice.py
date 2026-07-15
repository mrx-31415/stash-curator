from pathlib import Path

from curator.events import HistoricalEventStore
from curator.model import PreferenceModelBuilder, RecommendationModelStore
from curator.reporting import ReportGenerator
from curator.storage import MigrationRunner, connect_database
from curator.sync import SyncService
from curator.sync.repository import SyncRepository
from tests.integration.test_sync import SyntheticClient, _entities


def test_synthetic_sync_build_and_report_validation_slice(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "curator.sqlite3")
    MigrationRunner(connection).migrate(applied_at_ms=1)
    synced = SyncService(
        SyntheticClient(_entities()),
        SyncRepository(connection),
        page_size=1,
        clock_ms=lambda: 1_800_000_000_000,
        id_factory=lambda: "validation-sync",
    ).sync(full=True)

    history = HistoricalEventStore(connection).rebuild()
    model = PreferenceModelBuilder(connection, clock_ms=lambda: 1_800_000_000_000).build()
    report_path = tmp_path / "validation-report.html"
    report = ReportGenerator(connection).generate(report_path, count=2, redacted=True)

    assert synced.entity_counts["scene"] == 2
    assert history.session_count == 2
    assert history.outcome_count == 2
    assert model.scene_count == 2
    assert RecommendationModelStore(connection).current_model_id() == model.model_id
    assert report.model_id == model.model_id
    assert set(report.lane_counts) == {
        "for_you",
        "best_bets",
        "revisit",
        "discover",
        "adventure",
    }
    assert report_path.read_text(encoding="utf-8").startswith("<!doctype html>")

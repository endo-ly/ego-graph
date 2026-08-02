"""Catalog schema 契約と Backend 手書き fixture の照合テスト。

fixture は既存の手書き定義（conftest.py）を維持し、カタログから自動生成しない。
カタログと実出力の照合は Pipelines 保存時の検証（同一の canonical 変換）が担う。
"""

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from dataset_catalog import DatasetDefinition, datasets
from dataset_catalog.canonical import arrow_type_to_canonical, type_mismatch

# (dataset, fixture名, fixture wrapper の parquet path 属性) の組。
# カタログに無い fixture 列は契約対象外で、既存SQLが参照する実カラムのまま維持する。
FIXTURE_CASES = [
    pytest.param(
        datasets.SPOTIFY_PLAYS,
        "duckdb_with_sample_data",
        "test_parquet_path",
        id="spotify.plays",
    ),
    pytest.param(
        datasets.YOUTUBE_WATCH_EVENTS,
        "youtube_with_sample_data",
        "test_watch_events_parquet_path",
        id="youtube.watch_events",
    ),
    pytest.param(
        datasets.YOUTUBE_VIDEOS,
        "youtube_with_sample_data",
        "test_videos_parquet_path",
        id="youtube.videos",
    ),
    pytest.param(
        datasets.YOUTUBE_CHANNELS,
        "youtube_with_sample_data",
        "test_channels_parquet_path",
        id="youtube.channels",
    ),
    pytest.param(
        datasets.BROWSER_HISTORY_PAGE_VIEWS,
        "browser_history_with_sample_data",
        "test_page_views_parquet_path",
        id="browser_history.page_views",
    ),
    pytest.param(
        datasets.GITHUB_PULL_REQUESTS,
        "github_with_sample_data",
        "test_prs_parquet_path",
        id="github.pull_requests",
    ),
    pytest.param(
        datasets.GITHUB_COMMITS,
        "github_with_sample_data",
        "test_commits_parquet_path",
        id="github.commits",
    ),
    pytest.param(
        datasets.GITHUB_REPOSITORIES,
        "github_with_sample_data",
        "test_repos_parquet_path",
        id="github.repositories",
    ),
]


def _fixture_parquet_path(request, fixture_name: str, path_attr: str) -> Path:
    wrapper = request.getfixturevalue(fixture_name)
    return Path(getattr(wrapper, path_attr))


@pytest.mark.parametrize(
    ("dataset", "fixture_name", "path_attr"),
    FIXTURE_CASES,
)
def test_fixture_parquet_satisfies_catalog_contract(
    dataset: DatasetDefinition,
    fixture_name: str,
    path_attr: str,
    request,
):
    """fixture parquet が required columns と canonical type 契約を満たす。"""
    # Arrange
    parquet_path = _fixture_parquet_path(request, fixture_name, path_attr)

    # Act
    fields = {field.name: field.type for field in pq.read_schema(parquet_path)}

    # Assert
    for column in dataset.required_columns:
        assert column in fields, (
            f"{dataset.dataset_id}: required column が fixture に無い: {column}"
        )
    for column, expected in dataset.column_types.items():
        field = pq.read_schema(parquet_path).field(column)
        actual = arrow_type_to_canonical(field.type)
        mismatch = type_mismatch(expected, actual)
        assert mismatch is None, f"{dataset.dataset_id}.{column}: {mismatch}"


@pytest.mark.parametrize(
    ("dataset", "fixture_name", "path_attr"),
    FIXTURE_CASES,
)
def test_fixture_parquet_supports_representative_query(
    dataset: DatasetDefinition,
    fixture_name: str,
    path_attr: str,
    request,
):
    """fixture parquet に対して契約カラムを使った代表クエリが実行できる。"""
    # Arrange
    parquet_path = _fixture_parquet_path(request, fixture_name, path_attr)
    conn = request.getfixturevalue(fixture_name)
    columns = ", ".join(f'"{column}"' for column in dataset.required_columns)
    query = f"SELECT {columns} FROM read_parquet(?) LIMIT 1"

    # Act
    count = conn.execute(
        "SELECT count(*) FROM read_parquet(?)", (str(parquet_path),)
    ).fetchone()[0]
    rows = conn.execute(query, (str(parquet_path),)).fetchall()

    # Assert
    assert count > 0
    assert len(rows) == 1

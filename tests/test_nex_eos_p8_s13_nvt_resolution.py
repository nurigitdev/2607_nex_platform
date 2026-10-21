from __future__ import annotations

import pytest
from nex_eos import (
    EOS_METADATA,
    EosProjectError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
)
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NVT_A = "51000000-0000-4000-8000-000000000001"
NVT_B = "51000000-0000-4000-8000-000000000002"
MOTHER_A = "52000000-0000-4000-8000-000000000001"
CHILD_A = "52000000-0000-4000-8000-000000000002"
DEEP_A = "52000000-0000-4000-8000-000000000003"
MOTHER_B = "52000000-0000-4000-8000-000000000004"


@pytest.fixture
def repository() -> SqlAlchemyEosProjectRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return SqlAlchemyEosProjectRepository(sessionmaker(bind=engine))


def _seed(repository: SqlAlchemyEosProjectRepository) -> None:
    repository.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_A, "NVT-A", "NVT A")
    )
    repository.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_B, "NVT-B", "NVT B")
    )
    repository.create_nvt_project(
        NvtProjectInput("tenant-b", NVT_A, "NVT-A", "Other tenant")
    )
    for value in (
        ProjectInput("tenant-a", MOTHER_A, "MOTHER-A", "Mother A", nvt_project_id=NVT_A),
        ProjectInput("tenant-a", CHILD_A, "CHILD-A", "Child A", parent_project_id=MOTHER_A),
        ProjectInput("tenant-a", DEEP_A, "DEEP-A", "Deep A", parent_project_id=CHILD_A),
        ProjectInput("tenant-a", MOTHER_B, "MOTHER-B", "Mother B", nvt_project_id=NVT_A),
        ProjectInput("tenant-b", MOTHER_A, "MOTHER-A", "Other Mother", nvt_project_id=NVT_A),
    ):
        repository.create_project(value)


def test_nvt_query_returns_multiple_mothers_and_all_descendants(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed(repository)
    projects = repository.list_projects_for_nvt(
        tenant_id="tenant-a", nvt_project_id=NVT_A
    )

    assert [item["project_id"] for item in projects] == [
        MOTHER_A,
        MOTHER_B,
        CHILD_A,
        DEEP_A,
    ]
    assert [item["hierarchy_depth"] for item in projects] == [1, 1, 2, 3]


def test_descendant_resolves_to_nvt_and_tenant_isolation_holds(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed(repository)

    resolved = repository.resolve_nvt_project(
        tenant_id="tenant-a", project_id=DEEP_A
    )
    assert resolved is not None
    assert resolved["nvt_project_id"] == NVT_A
    assert resolved["tenant_id"] == "tenant-a"
    assert repository.resolve_nvt_project(
        tenant_id="tenant-b", project_id=DEEP_A
    ) is None


def test_empty_nvt_wrong_scope_and_result_limit_are_bounded(
    repository: SqlAlchemyEosProjectRepository,
) -> None:
    _seed(repository)
    assert repository.list_projects_for_nvt(
        tenant_id="tenant-a", nvt_project_id=NVT_B
    ) == []
    assert repository.list_projects_for_nvt(
        tenant_id="tenant-b", nvt_project_id=NVT_B
    ) == []
    assert len(
        repository.list_projects_for_nvt(
            tenant_id="tenant-a", nvt_project_id=NVT_A, limit=2
        )
    ) == 2


@pytest.mark.parametrize("limit", (0, 1001, True, "10"))
def test_nvt_query_rejects_invalid_limits(
    repository: SqlAlchemyEosProjectRepository,
    limit,
) -> None:
    with pytest.raises(EosProjectError) as error:
        repository.list_projects_for_nvt(
            tenant_id="tenant-a", nvt_project_id=NVT_A, limit=limit
        )
    assert error.value.error_code == "EOS_PROJECT_INVALID"


def test_resolution_database_failure_is_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private recursive query")

    repository = SqlAlchemyEosProjectRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    for operation in (
        lambda: repository.list_projects_for_nvt(
            tenant_id="tenant-a", nvt_project_id=NVT_A
        ),
        lambda: repository.resolve_nvt_project(
            tenant_id="tenant-a", project_id=MOTHER_A
        ),
    ):
        with pytest.raises(EosProjectError) as error:
            operation()
        assert error.value.error_code == "EOS_PROJECT_PERSISTENCE_FAILED"
        assert "private recursive query" not in error.value.detail


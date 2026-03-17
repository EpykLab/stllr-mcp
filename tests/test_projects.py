"""Tests for project MCP tools."""

import pytest
from unittest.mock import MagicMock, patch

import stellarbridge_mcp.tools.projects as projects_module
from stellarbridge_mcp.tools.projects import (
    list_projects,
    create_project,
    delete_project,
)


@pytest.fixture()
def mock_client() -> MagicMock:
    client = MagicMock()
    with patch.object(projects_module, "get_client", return_value=client):
        yield client


class TestListProjects:
    def test_returns_projects(self, mock_client: MagicMock) -> None:
        mock_client.list_projects.return_value = [
            {"id": 1, "name": "Project A"},
            {"id": 2, "name": "Project B"},
        ]
        result = list_projects()
        mock_client.list_projects.assert_called_once_with()
        assert len(result) == 2
        assert result[0]["name"] == "Project A"

    def test_returns_empty_list(self, mock_client: MagicMock) -> None:
        mock_client.list_projects.return_value = []
        result = list_projects()
        assert result == []


class TestCreateProject:
    def test_creates_with_name_and_partners(self, mock_client: MagicMock) -> None:
        mock_client.create_project.return_value = {"id": 10, "name": "New Project"}
        result = create_project(name="New Project", partner_ids=[1, 2])
        mock_client.create_project.assert_called_once_with("New Project", [1, 2])
        assert result["id"] == 10

    def test_creates_with_single_partner(self, mock_client: MagicMock) -> None:
        mock_client.create_project.return_value = {"id": 5}
        create_project(name="Solo", partner_ids=[99])
        mock_client.create_project.assert_called_once_with("Solo", [99])


class TestDeleteProject:
    def test_deletes_by_id(self, mock_client: MagicMock) -> None:
        mock_client.delete_project.return_value = None
        delete_project(project_id=7)
        mock_client.delete_project.assert_called_once_with(7)

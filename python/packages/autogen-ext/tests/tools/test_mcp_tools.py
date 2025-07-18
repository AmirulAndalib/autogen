import asyncio
import logging
import os
import threading
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from _pytest.logging import LogCaptureFixture  # type: ignore[import]
from autogen_core import CancellationToken
from autogen_core.tools import Workbench
from autogen_core.utils import schema_to_pydantic_model
from autogen_ext.tools.mcp import (
    McpSessionActor,
    McpWorkbench,
    SseMcpToolAdapter,
    SseServerParams,
    StdioMcpToolAdapter,
    StdioServerParams,
    StreamableHttpMcpToolAdapter,
    StreamableHttpServerParams,
    create_mcp_server_session,
    mcp_server_tools,
)
from mcp import ClientSession, Tool
from mcp.types import (
    Annotations,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)
from pydantic.networks import AnyUrl


@pytest.fixture
def sample_tool() -> Tool:
    return Tool(
        name="test_tool",
        description="A test tool",
        inputSchema={
            "type": "object",
            "properties": {"test_param": {"type": "string"}},
            "required": ["test_param"],
        },
    )


@pytest.fixture
def sample_server_params() -> StdioServerParams:
    return StdioServerParams(command="echo", args=["test"])


@pytest.fixture
def sample_sse_tool() -> Tool:
    return Tool(
        name="test_sse_tool",
        description="A test SSE tool",
        inputSchema={
            "type": "object",
            "properties": {"test_param": {"type": "string"}},
            "required": ["test_param"],
        },
    )


@pytest.fixture
def sample_streamable_http_tool() -> Tool:
    return Tool(
        name="test_streamable_http_tool",
        description="A test StreamableHttp tool",
        inputSchema={
            "type": "object",
            "properties": {"test_param": {"type": "string"}},
            "required": ["test_param"],
        },
    )


@pytest.fixture
def mock_sse_session() -> AsyncMock:
    session = AsyncMock(spec=ClientSession)
    session.initialize = AsyncMock()
    session.call_tool = AsyncMock()
    session.list_tools = AsyncMock()
    return session


@pytest.fixture
def mock_streamable_http_session() -> AsyncMock:
    session = AsyncMock(spec=ClientSession)
    session.initialize = AsyncMock()
    session.call_tool = AsyncMock()
    session.list_tools = AsyncMock()
    return session


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock(spec=ClientSession)
    session.initialize = AsyncMock()
    session.call_tool = AsyncMock()
    session.list_tools = AsyncMock()
    return session


@pytest.fixture
def mock_tool_response() -> MagicMock:
    response = MagicMock()
    response.isError = False
    response.content = [
        TextContent(
            text="test_output",
            type="text",
            annotations=Annotations(audience=["user", "assistant"], priority=0.7),
        ),
    ]
    return response


@pytest.fixture
def cancellation_token() -> CancellationToken:
    return CancellationToken()


@pytest.fixture
def mock_error_tool_response() -> MagicMock:
    response = MagicMock()
    response.isError = True
    response.content = [TextContent(text="error output", type="text")]
    return response


def test_adapter_config_serialization(sample_tool: Tool, sample_server_params: StdioServerParams) -> None:
    """Test that adapter can be saved to and loaded from config."""
    original_adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool)
    config = original_adapter.dump_component()
    loaded_adapter = StdioMcpToolAdapter.load_component(config)

    # Test that the loaded adapter has the same properties
    assert loaded_adapter.name == "test_tool"
    assert loaded_adapter.description == "A test tool"

    # Verify schema structure
    schema = loaded_adapter.schema
    assert "parameters" in schema, "Schema must have parameters"
    params_schema = schema["parameters"]
    assert isinstance(params_schema, dict), "Parameters must be a dict"
    assert "type" in params_schema, "Parameters must have type"
    assert "required" in params_schema, "Parameters must have required fields"
    assert "properties" in params_schema, "Parameters must have properties"

    # Compare schema content
    assert params_schema["type"] == sample_tool.inputSchema["type"]
    assert params_schema["required"] == sample_tool.inputSchema["required"]
    assert (
        params_schema["properties"]["test_param"]["type"] == sample_tool.inputSchema["properties"]["test_param"]["type"]
    )


@pytest.mark.asyncio
async def test_mcp_tool_execution(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    mock_tool_response: MagicMock,
    cancellation_token: CancellationToken,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that adapter properly executes tools through ClientSession."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )

    mock_session.call_tool.return_value = mock_tool_response

    with caplog.at_level(logging.INFO):
        adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool)
        result = await adapter.run_json(
            args=schema_to_pydantic_model(sample_tool.inputSchema)(**{"test_param": "test"}).model_dump(),
            cancellation_token=cancellation_token,
        )

        assert result == mock_tool_response.content
        mock_session.initialize.assert_called_once()
        mock_session.call_tool.assert_called_once()

        # Check log.
        assert "test_output" in caplog.text


@pytest.mark.asyncio
async def test_adapter_from_server_params(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that adapter can be created from server parameters."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )

    mock_session.list_tools.return_value.tools = [sample_tool]

    adapter = await StdioMcpToolAdapter.from_server_params(sample_server_params, "test_tool")

    assert isinstance(adapter, StdioMcpToolAdapter)
    assert adapter.name == "test_tool"
    assert adapter.description == "A test tool"

    # Verify schema structure
    schema = adapter.schema
    assert "parameters" in schema, "Schema must have parameters"
    params_schema = schema["parameters"]
    assert isinstance(params_schema, dict), "Parameters must be a dict"
    assert "type" in params_schema, "Parameters must have type"
    assert "required" in params_schema, "Parameters must have required fields"
    assert "properties" in params_schema, "Parameters must have properties"

    # Compare schema content
    assert params_schema["type"] == sample_tool.inputSchema["type"]
    assert params_schema["required"] == sample_tool.inputSchema["required"]
    assert (
        params_schema["properties"]["test_param"]["type"] == sample_tool.inputSchema["properties"]["test_param"]["type"]
    )


@pytest.mark.asyncio
async def test_adapter_from_server_params_with_return_value_as_string(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that adapter can be created from server parameters."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )
    mock_session.list_tools.return_value.tools = [sample_tool]

    adapter = await StdioMcpToolAdapter.from_server_params(sample_server_params, "test_tool")

    assert (
        adapter.return_value_as_string(
            [
                TextContent(
                    text="this is a sample text",
                    type="text",
                    annotations=Annotations(audience=["user", "assistant"], priority=0.7),
                ),
                ImageContent(
                    data="this is a sample base64 encoded image",
                    mimeType="image/png",
                    type="image",
                    annotations=None,
                ),
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        text="this is a sample text",
                        uri=AnyUrl(url="http://example.com/test"),
                    ),
                    annotations=Annotations(audience=["user"], priority=0.3),
                ),
            ]
        )
        == '[{"type": "text", "text": "this is a sample text", "annotations": {"audience": ["user", "assistant"], "priority": 0.7}}, {"type": "image", "data": "this is a sample base64 encoded image", "mimeType": "image/png", "annotations": null}, {"type": "resource", "resource": {"uri": "http://example.com/test", "mimeType": null, "text": "this is a sample text"}, "annotations": {"audience": ["user"], "priority": 0.3}}]'
    )


@pytest.mark.asyncio
async def test_adapter_from_factory(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that factory function returns a list of tools."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._factory.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )
    mock_session.list_tools.return_value.tools = [sample_tool]
    tools = await mcp_server_tools(server_params=sample_server_params)
    assert tools is not None
    assert len(tools) > 0
    assert isinstance(tools[0], StdioMcpToolAdapter)


@pytest.mark.asyncio
async def test_adapter_from_factory_existing_session(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that factory function returns a list of tools with an existing session."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._factory.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )
    mock_session.list_tools.return_value.tools = [sample_tool]
    tools = await mcp_server_tools(server_params=sample_server_params, session=mock_session)
    assert tools is not None
    assert len(tools) > 0
    assert isinstance(tools[0], StdioMcpToolAdapter)


@pytest.mark.asyncio
async def test_sse_adapter_config_serialization(sample_sse_tool: Tool) -> None:
    """Test that SSE adapter can be saved to and loaded from config."""
    params = SseServerParams(url="http://test-url")
    original_adapter = SseMcpToolAdapter(server_params=params, tool=sample_sse_tool)
    config = original_adapter.dump_component()
    loaded_adapter = SseMcpToolAdapter.load_component(config)

    # Test that the loaded adapter has the same properties
    assert loaded_adapter.name == "test_sse_tool"
    assert loaded_adapter.description == "A test SSE tool"

    # Verify schema structure
    schema = loaded_adapter.schema
    assert "parameters" in schema, "Schema must have parameters"
    params_schema = schema["parameters"]
    assert isinstance(params_schema, dict), "Parameters must be a dict"
    assert "type" in params_schema, "Parameters must have type"
    assert "required" in params_schema, "Parameters must have required fields"
    assert "properties" in params_schema, "Parameters must have properties"

    # Compare schema content
    assert params_schema["type"] == sample_sse_tool.inputSchema["type"]
    assert params_schema["required"] == sample_sse_tool.inputSchema["required"]
    assert (
        params_schema["properties"]["test_param"]["type"]
        == sample_sse_tool.inputSchema["properties"]["test_param"]["type"]
    )


@pytest.mark.asyncio
async def test_sse_tool_execution(
    sample_sse_tool: Tool,
    mock_sse_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that SSE adapter properly executes tools through ClientSession."""
    params = SseServerParams(url="http://test-url")
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_sse_session

    mock_sse_session.call_tool.return_value = MagicMock(
        isError=False,
        content=[
            TextContent(
                text="test_output",
                type="text",
                annotations=Annotations(audience=["user", "assistant"], priority=0.7),
            ),
        ],
    )

    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )

    with caplog.at_level(logging.INFO):
        adapter = SseMcpToolAdapter(server_params=params, tool=sample_sse_tool)
        result = await adapter.run_json(
            args=schema_to_pydantic_model(sample_sse_tool.inputSchema)(**{"test_param": "test"}).model_dump(),
            cancellation_token=CancellationToken(),
        )

        assert result == mock_sse_session.call_tool.return_value.content
        mock_sse_session.initialize.assert_called_once()
        mock_sse_session.call_tool.assert_called_once()

        # Check log.
        assert "test_output" in caplog.text


@pytest.mark.asyncio
async def test_sse_adapter_from_server_params(
    sample_sse_tool: Tool,
    mock_sse_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that SSE adapter can be created from server parameters."""
    params = SseServerParams(url="http://test-url")
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_sse_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )

    mock_sse_session.list_tools.return_value.tools = [sample_sse_tool]

    adapter = await SseMcpToolAdapter.from_server_params(params, "test_sse_tool")

    assert isinstance(adapter, SseMcpToolAdapter)
    assert adapter.name == "test_sse_tool"
    assert adapter.description == "A test SSE tool"

    # Verify schema structure
    schema = adapter.schema
    assert "parameters" in schema, "Schema must have parameters"
    params_schema = schema["parameters"]
    assert isinstance(params_schema, dict), "Parameters must be a dict"
    assert "type" in params_schema, "Parameters must have type"
    assert "required" in params_schema, "Parameters must have required fields"
    assert "properties" in params_schema, "Parameters must have properties"

    # Compare schema content
    assert params_schema["type"] == sample_sse_tool.inputSchema["type"]
    assert params_schema["required"] == sample_sse_tool.inputSchema["required"]
    assert (
        params_schema["properties"]["test_param"]["type"]
        == sample_sse_tool.inputSchema["properties"]["test_param"]["type"]
    )


@pytest.mark.asyncio
async def test_streamable_http_adapter_config_serialization(sample_streamable_http_tool: Tool) -> None:
    """Test that StreamableHttp adapter can be saved to and loaded from config."""
    params = StreamableHttpServerParams(url="http://test-url")
    original_adapter = StreamableHttpMcpToolAdapter(server_params=params, tool=sample_streamable_http_tool)
    config = original_adapter.dump_component()
    loaded_adapter = StreamableHttpMcpToolAdapter.load_component(config)

    # Test that the loaded adapter has the same properties
    assert loaded_adapter.name == "test_streamable_http_tool"
    assert loaded_adapter.description == "A test StreamableHttp tool"

    # Verify schema structure
    schema = loaded_adapter.schema
    assert "parameters" in schema, "Schema must have parameters"
    params_schema = schema["parameters"]
    assert isinstance(params_schema, dict), "Parameters must be a dict"
    assert "type" in params_schema, "Parameters must have type"
    assert "required" in params_schema, "Parameters must have required fields"
    assert "properties" in params_schema, "Parameters must have properties"

    # Compare schema content
    assert params_schema["type"] == sample_streamable_http_tool.inputSchema["type"]
    assert params_schema["required"] == sample_streamable_http_tool.inputSchema["required"]
    assert (
        params_schema["properties"]["test_param"]["type"]
        == sample_streamable_http_tool.inputSchema["properties"]["test_param"]["type"]
    )


@pytest.mark.asyncio
async def test_streamable_http_tool_execution(
    sample_streamable_http_tool: Tool,
    mock_streamable_http_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that StreamableHttp adapter properly executes tools through ClientSession."""
    params = StreamableHttpServerParams(url="http://test-url")
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_streamable_http_session

    mock_streamable_http_session.call_tool.return_value = MagicMock(
        isError=False,
        content=[
            TextContent(
                text="test_output",
                type="text",
                annotations=Annotations(audience=["user", "assistant"], priority=0.7),
            ),
        ],
    )

    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )

    with caplog.at_level(logging.INFO):
        adapter = StreamableHttpMcpToolAdapter(server_params=params, tool=sample_streamable_http_tool)
        result = await adapter.run_json(
            args=schema_to_pydantic_model(sample_streamable_http_tool.inputSchema)(
                **{"test_param": "test"}
            ).model_dump(),
            cancellation_token=CancellationToken(),
        )

        assert result == mock_streamable_http_session.call_tool.return_value.content
        mock_streamable_http_session.initialize.assert_called_once()
        mock_streamable_http_session.call_tool.assert_called_once()

        # Check log.
        assert "test_output" in caplog.text


@pytest.mark.asyncio
async def test_streamable_http_adapter_from_server_params(
    sample_streamable_http_tool: Tool,
    mock_streamable_http_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that StreamableHttp adapter can be created from server parameters."""
    params = StreamableHttpServerParams(url="http://test-url")
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_streamable_http_session
    monkeypatch.setattr(
        "autogen_ext.tools.mcp._base.create_mcp_server_session",
        lambda *args, **kwargs: mock_context,  # type: ignore
    )

    mock_streamable_http_session.list_tools.return_value.tools = [sample_streamable_http_tool]

    adapter = await StreamableHttpMcpToolAdapter.from_server_params(params, "test_streamable_http_tool")

    assert isinstance(adapter, StreamableHttpMcpToolAdapter)
    assert adapter.name == "test_streamable_http_tool"
    assert adapter.description == "A test StreamableHttp tool"

    # Verify schema structure
    schema = adapter.schema
    assert "parameters" in schema, "Schema must have parameters"
    params_schema = schema["parameters"]
    assert isinstance(params_schema, dict), "Parameters must be a dict"
    assert "type" in params_schema, "Parameters must have type"
    assert "required" in params_schema, "Parameters must have required fields"
    assert "properties" in params_schema, "Parameters must have properties"

    # Compare schema content
    assert params_schema["type"] == sample_streamable_http_tool.inputSchema["type"]
    assert params_schema["required"] == sample_streamable_http_tool.inputSchema["required"]
    assert (
        params_schema["properties"]["test_param"]["type"]
        == sample_streamable_http_tool.inputSchema["properties"]["test_param"]["type"]
    )


@pytest.mark.asyncio
async def test_mcp_server_fetch() -> None:
    params = StdioServerParams(
        command="uvx",
        args=["mcp-server-fetch"],
        read_timeout_seconds=60,
    )
    tools = await mcp_server_tools(server_params=params)
    assert tools is not None
    assert tools[0].name == "fetch"
    result = await tools[0].run_json({"url": "https://github.com/"}, CancellationToken())
    assert result is not None


@pytest.mark.asyncio
async def test_mcp_server_filesystem() -> None:
    params = StdioServerParams(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            ".",
        ],
        read_timeout_seconds=60,
    )
    tools = await mcp_server_tools(server_params=params)
    assert tools is not None
    tools = [tool for tool in tools if tool.name == "read_file"]
    assert len(tools) == 1
    tool = tools[0]
    result = await tool.run_json({"path": "README.md"}, CancellationToken())
    assert result is not None


@pytest.mark.asyncio
async def test_mcp_server_git() -> None:
    params = StdioServerParams(
        command="uvx",
        args=["mcp-server-git"],
        read_timeout_seconds=60,
    )
    tools = await mcp_server_tools(server_params=params)
    assert tools is not None
    tools = [tool for tool in tools if tool.name == "git_log"]
    assert len(tools) == 1
    tool = tools[0]
    repo_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
    result = await tool.run_json({"repo_path": repo_path}, CancellationToken())
    assert result is not None


@pytest.mark.asyncio
async def test_mcp_server_git_existing_session() -> None:
    params = StdioServerParams(
        command="uvx",
        args=["mcp-server-git"],
        read_timeout_seconds=60,
    )
    async with create_mcp_server_session(params) as session:
        await session.initialize()
        tools = await mcp_server_tools(server_params=params, session=session)
        assert tools is not None
        git_log = [tool for tool in tools if tool.name == "git_log"][0]
        repo_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
        result = await git_log.run_json({"repo_path": repo_path}, CancellationToken())
        assert result is not None

        git_status = [tool for tool in tools if tool.name == "git_status"][0]
        result = await git_status.run_json({"repo_path": repo_path}, CancellationToken())
        assert result is not None


@pytest.mark.asyncio
async def test_mcp_server_github() -> None:
    # Check if GITHUB_TOKEN is set.
    if "GITHUB_TOKEN" not in os.environ:
        pytest.skip("GITHUB_TOKEN environment variable is not set. Skipping test.")
    params = StdioServerParams(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-github",
        ],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ["GITHUB_TOKEN"]},
        read_timeout_seconds=60,
    )
    tools = await mcp_server_tools(server_params=params)
    assert tools is not None
    tools = [tool for tool in tools if tool.name == "get_file_contents"]
    assert len(tools) == 1
    tool = tools[0]
    result = await tool.run_json(
        {"owner": "microsoft", "repo": "autogen", "path": "python", "branch": "main"},
        CancellationToken(),
    )
    assert result is not None


@pytest.mark.asyncio
async def test_mcp_workbench_start_stop() -> None:
    params = StdioServerParams(
        command="uvx",
        args=["mcp-server-fetch"],
        read_timeout_seconds=60,
    )

    workbench = McpWorkbench(params)
    assert workbench is not None
    assert workbench.server_params == params
    await workbench.start()
    assert workbench._actor is not None  # type: ignore[reportPrivateUsage]
    await workbench.stop()
    assert workbench._actor is None  # type: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_mcp_workbench_server_fetch() -> None:
    params = StdioServerParams(
        command="uvx",
        args=["mcp-server-fetch"],
        read_timeout_seconds=60,
    )

    workbench = McpWorkbench(server_params=params)
    await workbench.start()

    tools = await workbench.list_tools()
    assert tools is not None
    assert tools[0]["name"] == "fetch"

    result = await workbench.call_tool(tools[0]["name"], {"url": "https://github.com/"}, CancellationToken())
    assert result is not None

    await workbench.stop()


@pytest.mark.asyncio
async def test_mcp_workbench_server_filesystem() -> None:
    params = StdioServerParams(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            ".",
        ],
        read_timeout_seconds=60,
    )

    workbench = McpWorkbench(server_params=params)
    await workbench.start()

    tools = await workbench.list_tools()
    assert tools is not None
    tools = [tool for tool in tools if tool["name"] == "read_file"]
    assert len(tools) == 1
    tool = tools[0]
    result = await workbench.call_tool(tool["name"], {"path": "README.md"}, CancellationToken())
    assert result is not None

    await workbench.stop()

    # Serialize the workbench.
    config = workbench.dump_component()

    # Deserialize the workbench.
    async with Workbench.load_component(config) as new_workbench:
        tools = await new_workbench.list_tools()
        assert tools is not None
        tools = [tool for tool in tools if tool["name"] == "read_file"]
        assert len(tools) == 1
        tool = tools[0]
        result = await new_workbench.call_tool(tool["name"], {"path": "README.md"}, CancellationToken())
        assert result is not None


@pytest.mark.asyncio
async def test_lazy_init_and_finalize_cleanup() -> None:
    params = StdioServerParams(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            ".",
        ],
        read_timeout_seconds=60,
    )
    workbench = McpWorkbench(server_params=params)

    # Before any call, actor should not be initialized
    assert workbench._actor is None  # type: ignore[reportPrivateUsage]

    # Trigger list_tools → lazy start
    await workbench.list_tools()
    assert workbench._actor is not None  # type: ignore[reportPrivateUsage]
    assert workbench._actor._active is True  # type: ignore[reportPrivateUsage]

    actor = workbench._actor  # type: ignore[reportPrivateUsage]
    del workbench
    await asyncio.sleep(0.1)
    assert actor._active is False


@pytest.mark.asyncio
async def test_del_to_new_event_loop_when_get_event_loop_fails() -> None:
    params = StdioServerParams(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            ".",
        ],
        read_timeout_seconds=60,
    )
    workbench = McpWorkbench(server_params=params)

    await workbench.list_tools()
    assert workbench._actor is not None  # type: ignore[reportPrivateUsage]
    assert workbench._actor._active is True  # type: ignore[reportPrivateUsage]

    actor = workbench._actor  # type: ignore[reportPrivateUsage]

    def cleanup() -> None:
        nonlocal workbench
        del workbench

    t = threading.Thread(target=cleanup)
    t.start()
    t.join()

    await asyncio.sleep(0.1)
    assert actor._active is False  # type: ignore[reportPrivateUsage]


def test_del_raises_when_loop_closed() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    params = StdioServerParams(command="echo", args=["ok"])
    workbench = McpWorkbench(server_params=params)

    workbench._actor_loop = loop  # type: ignore[reportPrivateUsage]
    workbench._actor = cast(McpSessionActor, object())  # type: ignore[reportPrivateUsage]

    loop.close()

    with pytest.warns(RuntimeWarning, match="loop is closed or not running"):
        del workbench


def test_mcp_tool_adapter_normalize_payload(sample_tool: Tool, sample_server_params: StdioServerParams) -> None:
    """Test the _normalize_payload_to_content_list method of McpToolAdapter."""
    adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool)

    # Case 1: Payload is already a list of valid content items
    valid_content_list: list[TextContent | ImageContent | EmbeddedResource] = [
        TextContent(text="hello", type="text"),
        ImageContent(data="base64data", mimeType="image/png", type="image"),
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(text="embedded text", uri=AnyUrl(url="http://example.com/resource")),
        ),
    ]
    assert adapter._normalize_payload_to_content_list(valid_content_list) == valid_content_list  # type: ignore[reportPrivateUsage]

    # Case 2: Payload is a single TextContent
    single_text_content = TextContent(text="single text", type="text")
    assert adapter._normalize_payload_to_content_list(single_text_content) == [single_text_content]  # type: ignore[reportPrivateUsage, arg-type]

    # Case 3: Payload is a single ImageContent
    single_image_content = ImageContent(data="imagedata", mimeType="image/jpeg", type="image")
    assert adapter._normalize_payload_to_content_list(single_image_content) == [single_image_content]  # type: ignore[reportPrivateUsage, arg-type]

    # Case 4: Payload is a single EmbeddedResource
    single_embedded_resource = EmbeddedResource(
        type="resource",
        resource=TextResourceContents(text="other embedded", uri=AnyUrl(url="http://example.com/other")),
    )
    assert adapter._normalize_payload_to_content_list(single_embedded_resource) == [single_embedded_resource]  # type: ignore[reportPrivateUsage, arg-type]

    # Case 5: Payload is a string
    string_payload = "This is a string payload."
    expected_from_string = [TextContent(text=string_payload, type="text")]
    assert adapter._normalize_payload_to_content_list(string_payload) == expected_from_string  # type: ignore[reportPrivateUsage, arg-type]

    # Case 6: Payload is an integer
    int_payload = 12345
    expected_from_int = [TextContent(text=str(int_payload), type="text")]
    assert adapter._normalize_payload_to_content_list(int_payload) == expected_from_int  # type: ignore[reportPrivateUsage, arg-type]

    # Case 7: Payload is a dictionary
    dict_payload = {"key": "value", "number": 42}
    expected_from_dict = [TextContent(text=str(dict_payload), type="text")]
    assert adapter._normalize_payload_to_content_list(dict_payload) == expected_from_dict  # type: ignore[reportPrivateUsage, arg-type]

    # Case 8: Payload is an empty list (should still be a list of valid items, so returns as is)
    empty_list_payload: list[TextContent | ImageContent | EmbeddedResource] = []
    assert adapter._normalize_payload_to_content_list(empty_list_payload) == empty_list_payload  # type: ignore[reportPrivateUsage]

    # Case 9: Payload is None (should be stringified)
    none_payload = None
    expected_from_none = [TextContent(text=str(none_payload), type="text")]
    assert adapter._normalize_payload_to_content_list(none_payload) == expected_from_none  # type: ignore[reportPrivateUsage, arg-type]


@pytest.mark.asyncio
async def test_mcp_tool_adapter_run_error(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    mock_error_tool_response: MagicMock,
    cancellation_token: CancellationToken,
) -> None:
    """Test McpToolAdapter._run when tool returns an error."""
    adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool, session=mock_session)
    mock_session.call_tool.return_value = mock_error_tool_response

    args = {"test_param": "test_value"}
    with pytest.raises(Exception) as excinfo:
        await adapter._run(args=args, cancellation_token=cancellation_token, session=mock_session)  # type: ignore[reportPrivateUsage]

    mock_session.call_tool.assert_called_once_with(name=sample_tool.name, arguments=args)
    assert adapter.return_value_as_string([TextContent(text="error output", type="text")]) in str(excinfo.value)


@pytest.mark.asyncio
async def test_mcp_tool_adapter_run_cancelled_before_call(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    cancellation_token: CancellationToken,
) -> None:
    """Test McpToolAdapter._run when operation is cancelled before tool call."""
    adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool, session=mock_session)
    cancellation_token.cancel()  # Cancel before the call

    args = {"test_param": "test_value"}
    with pytest.raises(asyncio.CancelledError):
        await adapter._run(args=args, cancellation_token=cancellation_token, session=mock_session)  # type: ignore[reportPrivateUsage]

    mock_session.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_tool_adapter_run_cancelled_during_call(
    sample_tool: Tool,
    sample_server_params: StdioServerParams,
    mock_session: AsyncMock,
    cancellation_token: CancellationToken,
) -> None:
    """Test McpToolAdapter._run when operation is cancelled during tool call."""
    adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool, session=mock_session)
    mock_session.call_tool.side_effect = asyncio.CancelledError("Tool call cancelled")

    args = {"test_param": "test_value"}
    with pytest.raises(asyncio.CancelledError):
        await adapter._run(args=args, cancellation_token=cancellation_token, session=mock_session)  # type: ignore[reportPrivateUsage]

    mock_session.call_tool.assert_called_once_with(name=sample_tool.name, arguments=args)


def test_return_value_as_string_with_resource_link(sample_tool: Tool, sample_server_params: StdioServerParams) -> None:
    """Test return_value_as_string handles ResourceLink objects correctly."""
    adapter = StdioMcpToolAdapter(server_params=sample_server_params, tool=sample_tool)

    # Test ResourceLink with meta field
    resource_link = ResourceLink(
        name="test_link",
        type="resource_link",
        uri=AnyUrl(url="http://example.com"),
    )

    result = adapter.return_value_as_string([resource_link])
    # Verify the JSON serialization contains expected fields
    assert '"type": "resource_link"' in result
    assert '"name": "test_link"' in result
    assert '"uri": "http://example.com/"' in result  # AnyUrl normalizes with trailing slash

"""Authoritative-shadow workspace editing API."""

from .block_diff import (
    BlockEdit, DeleteBlock, InsertBlock, ReplaceBlock, ReuseBlock, diff_blocks,
)
from .block_schema import BlockLocation, BlockMap, BlockRecord, BlockSession, NestedRecord, PathStep
from .create import (
    Workspace, WorkspaceError, create_workspace, document_workspace_path,
    ensure_workspace, open_workspace,
)
from .shadow_blocks import BlockWarning, ShadowBlock, ShadowMetadataError, read_shadow_blocks

__all__ = [
    "BlockEdit", "BlockLocation", "BlockMap", "BlockRecord", "BlockSession",
    "BlockWarning", "DeleteBlock", "InsertBlock", "NestedRecord", "PathStep", "ReplaceBlock",
    "ReuseBlock", "ShadowBlock", "ShadowMetadataError", "Workspace", "WorkspaceError",
    "create_workspace", "diff_blocks", "document_workspace_path", "ensure_workspace",
    "open_workspace", "read_shadow_blocks",
]

"""Environment dispatch for the forward document builder."""


def handle_environment(builder, body, match, align, level, numfmt,
                       enum_depth, pstyle_id, pending_prefix):
    """Resolve one environment after the block scanner found its opener."""
    # The builder keeps these names as compatibility seams while the forward
    # document facade is being separated. The import is intentionally local:
    # ``write`` imports ``builder`` only after its seams are initialized.
    from . import write as api

    env = match.group(1)
    content_start = match.end()
    end_start, end_stop = api._find_env_end(body, env, content_start)
    if end_start == -1:
        builder.warnings.append(f"unterminated environment {env}")
        return len(body)
    content = body[content_start:end_start]
    if env in api.MATH_ENVS:
        return builder._handle_regular_environment(
            body, match, env, content, end_stop, align, level, numfmt,
            enum_depth, pstyle_id,
        )
    if env in api.LIST_ENVS:
        return builder._handle_list_environment(
            body, env, content, content_start, end_stop, align, level,
            numfmt, enum_depth, pstyle_id,
        )
    return builder._handle_regular_environment(
        body, match, env, content, end_stop, align, level, numfmt, enum_depth,
        pstyle_id,
    )

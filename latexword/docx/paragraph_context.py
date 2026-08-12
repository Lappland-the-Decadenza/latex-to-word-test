"""Mutable state for one paragraph import pass."""


class ParagraphContext:
    def __init__(
        self, p_el, warnings, rels, index, img_ctx, notes_ctx,
        comments_ctx, object_store, field_renderer, plain_run_renderer,
        hyperlink_renderer, opaque_renderer, alternate_renderer,
        drawing_renderer, pict_renderer,
    ):
        self.p_el = p_el
        self.warnings = warnings
        self.rels = rels or {}
        self.index = index
        self.img_ctx = img_ctx
        self.notes_ctx = notes_ctx
        self.comments_ctx = comments_ctx
        self.object_store = object_store
        self.field_renderer = field_renderer
        self.plain_run_renderer = plain_run_renderer
        self.hyperlink_renderer = hyperlink_renderer
        self.opaque_renderer = opaque_renderer
        self.alternate_renderer = alternate_renderer
        self.drawing_renderer = drawing_renderer
        self.pict_renderer = pict_renderer
        self.parts = []
        self.field_instr = None
        self.field_cached = []
        self.open_comment_ranges = {}
        self.run_index = 0
        self.text_offset = 0

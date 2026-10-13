class PipelineError(Exception):
    """A bill could not be processed. The message is shown to users, so keep it readable."""


class PdfReadError(PipelineError):
    pass


class OcrUnavailableError(PipelineError):
    pass


class ExtractionError(PipelineError):
    pass

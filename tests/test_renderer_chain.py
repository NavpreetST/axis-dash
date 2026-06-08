from aegis.renderer import QuotaExhausted, RendererError, TransientError


def test_exception_hierarchy():
    assert issubclass(QuotaExhausted, RendererError)
    assert issubclass(TransientError, RendererError)

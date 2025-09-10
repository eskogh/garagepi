def test_import():
    import garagepi
    assert hasattr(garagepi, "__version__")

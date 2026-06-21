from workloadiq.data import generator, loader


def test_csv_roundtrip(tmp_path):
    _, records = generator.generate(scenario="bigquery_bottleneck", hours=1)
    path = tmp_path / "t.csv"
    loader.write_csv(records, path)
    loaded = loader.read_csv(path)
    assert len(loaded) == len(records)
    a, b = records[0], loaded[0]
    assert a.metric_name == b.metric_name
    assert a.component_type == b.component_type
    assert abs(a.metric_value - b.metric_value) < 1e-6
    assert a.timestamp == b.timestamp


def test_pipeline_roundtrip(tmp_path):
    pipeline, _ = generator.generate(scenario="bigquery_bottleneck", hours=1)
    path = tmp_path / "p.json"
    loader.write_pipeline(pipeline, path)
    loaded = loader.read_pipeline(path)
    assert loaded.pipeline_id == pipeline.pipeline_id
    assert [s.sink_type for s in loaded.sinks] == [s.sink_type for s in pipeline.sinks]

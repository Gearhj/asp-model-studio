import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_current_statcast.mlb_regime_baseline import AuthorizedByteReader, read_safe_groups


def test_physical_allowlist_does_not_read_denied_read_ahead(tmp_path):
    path = tmp_path / 'range.bin'
    path.write_bytes(b'publicSEALEDfooter')
    reader = AuthorizedByteReader(path, [(0, 6), (12, 18)])
    assert reader.read() == b'public' + bytes(6) + b'footer'
    assert reader.physical_reads == [(0, 6), (12, 18)]
    reader.close()


def test_mixed_sealed_row_group_is_physically_excluded(tmp_path, monkeypatch):
    path = tmp_path / 'fixture.parquet'
    table = pa.table({'game_date': ['2026-08-06', '2026-08-07', '2026-08-07', '2026-08-14'],
                      'value': [1, 2, 3, 999]})
    pq.write_table(table, path, row_group_size=2)
    real_read = AuthorizedByteReader.read
    reads = []
    def tracked(self, size=-1):
        before = len(self.physical_reads)
        value = real_read(self, size)
        reads.extend(self.physical_reads[before:])
        return value
    monkeypatch.setattr(AuthorizedByteReader, 'read', tracked)
    actual, receipt = read_safe_groups(path)
    assert actual['value'].to_pylist() == [1, 2]
    assert receipt['rejectedRowGroups'][0]['rowGroup'] == 1
    metadata = pq.ParquetFile(path).metadata  # Synthetic fixture has no protected evidence.
    for index in range(metadata.row_group(1).num_columns):
        column = metadata.row_group(1).column(index)
        start = min(column.dictionary_page_offset, column.data_page_offset)
        end = start + column.total_compressed_size
        assert all(hi <= start or lo >= end for lo, hi in reads)

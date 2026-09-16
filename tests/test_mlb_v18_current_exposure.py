"""Only the accepted, physically separated old season authority may lack stats."""
import hashlib

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.sports_current_statcast.mlb_v18_current_exposure import (
    OLD_PA_SHA, PA_COLUMNS, _isolated_pa,
)
from server.sports_current_statcast.mlb_v18_current_sources import CurrentSourceError


def test_exposure_source_authority_does_not_open_unproven_current_dates(tmp_path):
    data = {column: ["fixture"] for column in PA_COLUMNS}
    data.update(gameDate=["2019-07-04"], season=[2019], mlbamGamePk=[1], atBatNumber=[1])
    historical = tmp_path / "accepted-season-separated.parquet"
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(data)), historical, write_statistics=False)
    blob = historical.read_bytes()
    descriptor = {"manifestSha256": OLD_PA_SHA, "seasons": ["2019"], "rows": 1,
                  "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
    assert len(_isolated_pa(historical, descriptor, "2019-07-04")) == 1
    # The historical source authorization cannot authorize an unproven current
    # partition, even when its name or caller-supplied day looks safe.
    with pytest.raises(CurrentSourceError, match="physically date-isolated"):
        _isolated_pa(historical, descriptor, "2026-08-13")
    with pytest.raises(CurrentSourceError, match="frozen boundary"):
        _isolated_pa(historical, descriptor, "2026-08-14")

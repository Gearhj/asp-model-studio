"""Focused metadata gate checks; these tests never load 2026 final scores."""
from pathlib import Path
import sys
import unittest
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.current_history_source import classify_current_metadata


class CurrentHistoryMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata=pd.read_parquet(ROOT/'outputs/nba-gen1-long-gap-v1/scope-metadata-2026.parquet')

    def test_real_metadata_complete_scope(self):
        result=classify_current_metadata(self.metadata)
        self.assertEqual(len(result['admittedGames']),1230)
        self.assertEqual(result['orientedTargetGames'],1225)
        self.assertEqual(result['neutralHistoryOnlyGames'],5)
        self.assertEqual(set(result['gamesPerTeam'].values()),{82})
        self.assertEqual(result['exclusionCounts'],{'PLAYOFFS':85,'PLAY_IN':6,'ALL_STAR':4,'POSTPONED_ORIGINAL_ID':4})
        self.assertEqual(len(result['contextOnlyEvents']),1)
        postponed=[r for r in result['excludedIdentities'] if r['reason']=='POSTPONED_ORIGINAL_ID']
        self.assertTrue(all('makeup_source_game_id' in r and not r['identity_merge_claimed'] for r in postponed))

    def test_outcomes_cannot_enter_metadata_pass(self):
        with self.assertRaisesRegex(ValueError,'metadata only'):
            classify_current_metadata(self.metadata.assign(home_score=0))

    def test_duplicate_ids_fail_closed(self):
        changed=pd.concat([self.metadata,self.metadata.iloc[[0]]],ignore_index=True)
        with self.assertRaisesRegex(ValueError,'unique'):
            classify_current_metadata(changed)

    def test_home_identity_mismatch_fails(self):
        changed=self.metadata.copy()
        eligible=(changed.season_type==2)&(changed.type_id==1)&changed.status_type_completed
        changed.loc[changed.index[eligible][0],'home_abbreviation']='BAD'
        with self.assertRaisesRegex(ValueError,'full name'):
            classify_current_metadata(changed)

    def test_date_orientation_is_new_york_calendar_not_utc_date(self):
        changed=self.metadata.copy()
        changed.loc[changed.index[0],'game_date']=pd.Timestamp('1900-01-01').date()
        with self.assertRaisesRegex(ValueError,'calendar dates'):
            classify_current_metadata(changed)

    def test_postponed_identity_is_not_silently_discarded(self):
        changed=self.metadata.copy()
        changed.loc[~changed.status_type_completed,'notes_headline']='Missing makeup date'
        with self.assertRaisesRegex(ValueError,'makeup-date note'):
            classify_current_metadata(changed)


if __name__=='__main__':unittest.main()

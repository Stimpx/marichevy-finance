"""v96 metadata against real, isolated PostgreSQL; no production/network access."""
import copy
import unittest
import uuid

import test_sync_database as db


def human_fixture():
    data = copy.deepcopy(db.FIXTURE)
    stamp = '2026-11-01T12:00:00.000Z'
    data['intelligence']['accounts'] = [{
        'id': 'fictional-own', 'name': 'Учебный счёт', 'amount': 80000,
        'snapshotDate': '2026-11-01', 'snapshotRevision': 'fictional-check',
        'updated_at': stamp, 'futureAccount': {'keep': [None, True, 'opaque']},
        'ledger': {'version': 1, 'enabled': True, 'startDate': '2026-11-01',
                   'openingBalance': 80000, 'kind': 'asset', 'includeInSpending': True},
        'snapshotVerification': {'amount': 80000, 'date': '2026-11-01',
                                 'revision': 'fictional-check', 'verifiedAt': stamp,
                                 'accountUpdatedAt': stamp}}]
    data['entries'] += [{
        'id': 'fictional-correction', 'type': 'transfer', 'amount': 15.25,
        'date': '2026-11-01', 'accountId': 'fictional-own',
        'balanceAdjustment': True, 'adjustmentDirection': 1,
        'reconciliationRevision': 'fictional-check', 'updated_at': stamp,
        'futureEntry': {'preserve': 'raw'}}, {
        'id': 'fictional-split-part', 'type': 'expense', 'amount': 50,
        'date': '2026-11-01', 'accountId': 'fictional-own',
        'splitGroupId': 'fictional-receipt', 'updated_at': stamp}]
    data['intelligence']['budgets'] += [{
        'id': 'v118-month:2026-11', 'kind': 'v118-month-plan', 'groupVersion': 3,
        'month': '2026-11', 'amount': 0, 'expectedIncome': 100000,
        'groupsComplete': True, 'incomeComplete': True,
        'groups': {'food': {'amount': 20000, 'flexible': True}},
        'periodPlan': {'fromDate': '2026-11-01', 'untilDate': '2026-11-10',
                       'everydayAmount': 20000, 'confirmed': True},
        'updated_at': stamp, 'futurePlan': {'keep': 42}}, {
        'id': 'fictional-seasonal', 'kind': 'v118-seasonal-reserve',
        'groupVersion': 3, 'amount': 12000, 'saved': 4000,
        'name': 'Учебная страховка', 'dueDate': '2027-01-15',
        'accountId': 'fictional-own', 'updated_at': stamp}]
    data['goals'] = [{'id': 'fictional-active-goal', 'target': 25000, 'saved': 10000,
                      'reserve': {'enabled': True, 'accountId': 'fictional-own', 'amount': 6000},
                      'deposits': [{'id': 'fictional-deposit', 'amount': 1000,
                                    'reserveDelta': 0, 'updated_at': stamp}],
                      'updated_at': stamp}]
    data['deletedGoals'] = {'fictional-archived-goal': stamp}
    data['deletedChores'] = {'fictional-completed-chore': stamp}
    data['chores'] = []
    data['settings']['preferences'] = {'humanArchive': {
        'goals': {'fictional-archived-goal': {
            'format': 'human-archive-v1', 'id': 'fictional-archived-goal',
            'status': 'archived', 'tombstone': stamp, 'archivedAt': stamp,
            'updated_at': stamp, 'record': {'id': 'fictional-archived-goal',
                                          'target': 5000, 'saved': 5000,
                                          'unknownGoal': {'preserve': True}}}},
        'chores': {'fictional-completed-chore': {
            'format': 'human-archive-v1', 'id': 'fictional-completed-chore',
            'status': 'archived', 'tombstone': stamp, 'archivedAt': stamp,
            'updated_at': stamp, 'record': {'id': 'fictional-completed-chore',
                                          'title': 'Учебное дело', 'due': '2026-11-01'}}}}}
    return data


class HumanBudgetDatabase(unittest.TestCase):
    docker = classmethod(db.SyncDatabaseTests.docker.__func__)
    sql = classmethod(db.SyncDatabaseTests.sql.__func__)
    as_user = classmethod(db.SyncDatabaseTests.as_user.__func__)
    cas = classmethod(db.SyncDatabaseTests.cas.__func__)
    setUpClass = classmethod(db.SyncDatabaseTests.setUpClass.__func__)
    setUp = db.SyncDatabaseTests.setUp
    activate = db.SyncDatabaseTests.activate
    snapshot = db.SyncDatabaseTests.snapshot

    def test_all_metadata_and_unknown_fields_survive_exact_jsonb_roundtrip(self):
        revision = self.activate()
        data = human_fixture()
        result = self.cas(revision, data)
        self.assertEqual(result['status'], 'written')
        self.assertEqual(result['data'], data)
        self.assertEqual(self.snapshot()['data'], data)
        self.assertEqual(self.snapshot()['protocol'], 2)

    def test_retry_cannot_duplicate_correction_split_or_archive(self):
        revision = self.activate()
        data = human_fixture()
        request = str(uuid.uuid4())
        first = self.cas(revision, data, request)
        self.assertEqual(self.cas(revision, data, request), first)
        self.assertEqual(self.snapshot()['revision'], revision + 1)
        self.assertEqual(self.snapshot()['data'], data)

    def test_stale_device_cannot_replace_confirmed_account_plan_or_archive(self):
        revision = self.activate()
        current = human_fixture()
        self.assertEqual(self.cas(revision, current)['status'], 'written')
        stale = copy.deepcopy(db.FIXTURE)
        stale['entries'].append({'id': 'fictional-other-device', 'amount': 7})
        conflict = self.cas(revision, stale)
        self.assertEqual(conflict['status'], 'conflict')
        self.assertEqual(conflict['data'], current)
        self.assertEqual(self.snapshot()['data'], current)
        merged = copy.deepcopy(conflict['data'])
        merged['entries'].append(stale['entries'][-1])
        self.assertEqual(self.cas(conflict['revision'], merged)['status'], 'written')
        self.assertEqual(self.snapshot()['data'], merged)

    def test_archive_restore_is_versioned_and_stale_archive_cannot_redelete(self):
        revision = self.activate()
        archived = human_fixture()
        ack = self.cas(revision, archived)
        restored = copy.deepcopy(archived)
        packet = restored['settings']['preferences']['humanArchive']['goals']['fictional-archived-goal']
        packet['status'] = 'restored'
        packet['updated_at'] = '2026-11-01T12:00:01.000Z'
        restored['goals'].append({**packet['record'], 'updated_at': packet['updated_at']})
        self.assertEqual(self.cas(ack['revision'], restored)['status'], 'written')
        before = self.snapshot()
        self.assertEqual(self.cas(ack['revision'], archived)['status'], 'conflict')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(before['data']['settings']['preferences']['humanArchive']['goals']
                         ['fictional-archived-goal']['record'], packet['record'])


if __name__ == '__main__':
    unittest.main()

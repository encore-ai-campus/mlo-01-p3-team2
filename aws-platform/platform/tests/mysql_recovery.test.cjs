// 실제 복구 코드에 가짜 MySQL/AdminAPI를 주입해 위험한 상황에서 쓰기가 없는지 검증한다.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {recoverCluster} = require('../roles/mysql_recovery/files/recovery.js');

function fixture(options = {}) {
  const config = {clusterName: 'infra', clusterId: 'cluster', groupUuid: 'group', port: 3306,
    user: 'failover', password: 'secret', nodes: [1, 2, 3].map(n => ({host: `10.0.0.${n}`, uuid: `uuid${n}`}))};
  const calls = [];
  let selected;
  let snapshots = 0;
  const topology = {};
  config.nodes.forEach((n, i) => {
    topology[n.host + ':3306'] = {status: options.degraded && i === 2 ? 'OFFLINE' : 'ONLINE', memberRole: i ? 'SECONDARY' : 'PRIMARY'};
  });
  const cluster = {status: () => ({defaultReplicaSet: {status: options.degraded ? 'OK_NO_TOLERANCE' : 'OK',
    topologyMode: 'Single-Primary', topology, primary: '10.0.0.1:3306'}})};
  const sessions = [];
  const api = {
    log: message => calls.push(['log', message]),
    shell: {connect: c => { selected = c.host; }},
    dba: {
      getCluster: () => cluster,
      rebootClusterFromCompleteOutage: (name, args) => {
        calls.push(['reboot', selected, args]);
        assert.equal(name, 'infra');
        assert.ok(!args || !('force' in args));
        if (options.dryRunError && args?.dryRun) throw new Error('AdminAPI refused');
        if (!args?.dryRun && options.incompleteRecovery) topology['10.0.0.3:3306'].status = 'RECOVERING';
        return cluster;
      }
    },
    mysql: {getSession: c => {
      const i = config.nodes.findIndex(n => n.host === c.host);
      if (options.unreachable === i) throw new Error('connection failed');
      const s = {closed: false, close() { this.closed = true; }, runSql(sql, args) {
        let rows;
        if (sql.startsWith('SELECT @@server_uuid')) {
          snapshots++;
          rows = [[options.wrongIdentity && i === 1 ? 'wrong' : `uuid${i + 1}`,
            options.gtid?.[i] || '1,2', 'group', 'MYSQL', 1, options.writable ? 0 : 1, '/var/lib/mysql/', options.purged?.[i] || '']];
          if (options.race && snapshots > 3) rows[0][1] += ',99';
        } else if (sql.includes('GTID_SUBSET')) {
          rows = [[Number(args[0].split(',').filter(Boolean).every(x => args[1].split(',').includes(x)))]];
        } else if (sql.includes('metadata.clusters')) {
          rows = [[options.wrongMetadata ? 'other' : 'cluster', 'infra', 'gr']];
        } else if (sql.includes('metadata.instances')) {
          rows = config.nodes.map(n => [n.uuid, n.host + ':3306']);
          if (options.extraMember) rows.push(['uuid4', '10.0.0.4:3306']);
        } else if (sql.includes('replication_group_members')) {
          rows = options.healthy || options.degraded
            ? config.nodes.map((n, j) => [n.uuid, options.degraded && j === 2 ? 'OFFLINE' : 'ONLINE', j ? 'SECONDARY' : 'PRIMARY'])
            : [[`uuid${i + 1}`, options.recovering && i === 1 ? 'RECOVERING' : 'OFFLINE', '']];
        } else throw new Error('unexpected SQL: ' + sql);
        return {fetchOne: () => rows[0], fetchAll: () => rows};
      }};
      sessions.push(s);
      return s;
    }}
  };
  return {config, api, calls, sessions};
}

test('healthy cluster: no reboot API call', () => {
  const f = fixture({healthy: true});
  assert.equal(recoverCluster(f.config, f.api, false), 'healthy');
  assert.equal(f.calls.filter(c => c[0] === 'reboot').length, 0);
});
test('full outage: select GTID superset on mysql-2, dry-run before recovery', () => {
  const f = fixture({gtid: ['1', '1,2,3', '1,2']});
  assert.equal(recoverCluster(f.config, f.api, false), 'recovered');
  assert.deepEqual(f.calls.filter(c => c[0] === 'reboot'), [
    ['reboot', '10.0.0.2', {dryRun: true}], ['reboot', '10.0.0.2', undefined]]);
  assert.ok(f.sessions.every(s => s.closed));
});
test('check-only never mutates', () => {
  const f = fixture();
  assert.equal(recoverCluster(f.config, f.api, true), 'dry-run');
  assert.equal(f.calls.filter(c => c[0] === 'reboot' && !c[2]?.dryRun).length, 0);
});
for (const [name, options, error] of [
  ['unreachable', {unreachable: 1}, /connection failed/],
  ['divergent GTID', {gtid: ['1,2', '1,3', '1']}, /DIVERGENT_GTID/],
  ['required binlog purged', {gtid: ['1,2', '1', '1'], purged: ['1,2', '1', '1']}, /MISSING_BINLOG/],
  ['unknown member', {extraMember: true}, /MEMBERSHIP_MISMATCH/],
  ['wrong server', {wrongIdentity: true}, /SERVER_IDENTITY/],
  ['wrong cluster metadata', {wrongMetadata: true}, /METADATA/],
  ['partial outage', {degraded: true}, /NOT_FULLY_HEALTHY/],
  ['still recovering', {recovering: true}, /NOT_A_COMPLETE/],
  ['offline but writable', {writable: true}, /NOT_A_COMPLETE/],
  ['state changed after dry-run', {race: true}, /STATE_CHANGED/],
  ['AdminAPI rejects dry-run', {dryRunError: true}, /AdminAPI refused/]
]) test(name + ': refuse writes and close sessions', () => {
  const f = fixture(options);
  assert.throws(() => recoverCluster(f.config, f.api, false), error);
  assert.equal(f.calls.filter(c => c[0] === 'reboot' && !c[2]?.dryRun).length, 0);
  assert.ok(f.sessions.every(s => s.closed));
});
test('incomplete recovery cannot report success', () => {
  const f = fixture({incompleteRecovery: true});
  assert.throws(() => recoverCluster(f.config, f.api, false), /MEMBER_NOT_ONLINE/);
  assert.equal(f.calls.filter(c => c[0] === 'log' && c[1].startsWith('RECOVERED')).length, 0);
});

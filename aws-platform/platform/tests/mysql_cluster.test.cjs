// 렌더링된 실제 템플릿을 AdminAPI 모의 객체로 실행한다. 서버와 DB에는 접속하지 않는다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const templates = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const addresses = ['10.30.20.11:3306', '10.50.20.11:3306', '10.20.20.11:3306'];
let passed = 0;

function run(options = {}) {
  const calls = [];
  const topology = {};
  const primary = options.primary || addresses[0];
  for (const address of (options.members || addresses)) {
    topology[address] = {status: 'ONLINE', memberRole: address === primary ? 'PRIMARY' : 'SECONDARY'};
  }
  if (options.offline) topology[options.offline].status = 'OFFLINE';
  if (options.recovering) topology[options.recovering].status = 'RECOVERING';
  if (options.errorMember) topology[options.errorMember].status = 'ERROR';
  const cluster = {
    status: () => ({defaultReplicaSet: {topology, primary, topologyMode: options.multi ? 'Multi-Primary' : 'Single-Primary', status: options.noQuorum ? 'NO_QUORUM' : 'OK'}}),
    addInstance: (uri, config) => {
      calls.push(['add', uri, config]);
      assert.equal(config.recoveryMethod, 'clone');
      const address = uri.slice(uri.lastIndexOf('@') + 1);
      topology[address] = {status: 'ONLINE', memberRole: 'SECONDARY'};
    },
    rejoinInstance: (uri, config) => {
      calls.push(['rejoin', uri, config]);
      assert.equal(config.recoveryMethod, 'incremental');
    },
    setupRouterAccount: (user, config) => calls.push(['router', user, config])
  };
  const session = {
    runSql: sql => ({fetchOne: () => [sql.includes('communication_stack') ? (options.stack || 'MYSQL') : sql.includes('schemata') ? Number(options.metadata !== false) : sql.includes('replication_group_members') ? Number(options.unmanaged || false) : Number(options.routerExists || false)]})
  };
  const context = {
    shell: {
      connect: connection => {
        if (options.authFailure) throw new Error('authentication failed');
        calls.push(['connect', connection.host]);
      },
      getSession: () => session
    },
    dba: {
      getCluster: name => {
        assert.equal(name, 'infra');
        if (options.replicaSet) throw new Error('ReplicaSet metadata is not a Cluster');
        return cluster;
      },
      createCluster: (name, config) => {
        calls.push(['create', name, config]);
        assert.equal(config.communicationStack, 'MYSQL');
        assert.equal(config.multiPrimary, false);
        assert.equal(config.manualStartOnBoot, false);
        assert.equal(config.consistency, 'BEFORE_ON_PRIMARY_FAILOVER');
        assert.equal(config.autoRejoinTries, 3);
        for (const address of addresses.slice(1)) delete topology[address];
        return cluster;
      },
      checkInstanceConfiguration: connection => {
        // 실제 AdminAPI가 거부한 로컬 root 접속을 모의 검사에서도 놓치지 않는다.
        if (connection.user === 'root') throw new Error("User 'root' can only connect from 'localhost'.");
        assert.equal(connection.scheme, 'mysql');
        assert.equal(connection.user, 'failover');
        assert.equal(connection.host, addresses[0].split(':')[0]);
        assert.equal(connection.port, 3306);
        assert.equal(connection.password, 'ValidP8!/%');
        assert.ok(!('socket' in connection));
        calls.push(['check-config', connection]);
        return {status: options.needsConfig ? 'error' : 'ok'};
      },
      configureInstance: (connection, config) => calls.push(['configure', connection, config])
    },
    mysql: {
      getSession: () => ({
        runSql: sql => ({fetchOne: () => [sql.includes('NOT IN') ? (options.candidateData || 0) : (options.candidateMetadata || 0)]}),
        close: () => calls.push(['close'])
      })
    },
    print: message => calls.push(['print', message])
  };
  let error;
  try {
    vm.runInNewContext(templates[options.template || 'cluster.js.j2'], context, {timeout: 1000});
  } catch (caught) {
    error = caught;
  }
  return {calls, error};
}

function check(name, options, verify) {
  verify(run(options));
  passed++;
  console.log('PASS ' + name);
}

check('fresh cluster creates one seed and clones two nodes', {metadata: false}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => c[0] === 'create').length, 1);
  assert.equal(calls.filter(c => c[0] === 'add').length, 2);
});
check('healthy rerun makes no cluster changes', {}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => ['create', 'add', 'rejoin'].includes(c[0])).length, 0);
});
check('primary change follows actual primary', {primary: addresses[1]}, ({calls, error}) => {
  assert.ifError(error);
  assert.deepEqual(calls.filter(c => c[0] === 'connect').map(c => c[1]), ['10.30.20.11', '10.50.20.11']);
});
check('missing member is added', {members: addresses.slice(0, 2)}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => c[0] === 'add').length, 1);
});
check('offline member rejoins incrementally', {offline: addresses[2]}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => c[0] === 'rejoin').length, 1);
});
check('recovering member is left to finish recovery', {recovering: addresses[2]}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => ['add', 'rejoin'].includes(c[0])).length, 0);
});
for (const [name, options] of [
  ['ReplicaSet is refused', {replicaSet: true}],
  ['authentication failure is refused', {authFailure: true}],
  ['quorum loss is refused', {noQuorum: true}],
  ['multi-primary is refused', {multi: true}],
  ['unmanaged GR is refused', {metadata: false, unmanaged: true}],
  ['unexpected existing member is refused', {members: [...addresses, '10.10.20.99:3306']}],
  ['candidate data is protected', {members: addresses.slice(0, 2), candidateData: 1}],
  ['candidate metadata is protected', {members: addresses.slice(0, 2), candidateMetadata: 1}],
  ['member ERROR requires inspection', {errorMember: addresses[2]}]
]) {
  check(name, options, ({calls, error}) => {
    assert.ok(error);
    assert.equal(calls.filter(c => ['create', 'add', 'rejoin'].includes(c[0])).length, 0);
  });
}
check('valid instance skips reconfiguration', {template: 'configure-instance.js.j2'}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => c[0] === 'check-config').length, 1);
  assert.equal(calls.filter(c => c[0] === 'configure').length, 0);
});
check('invalid instance requests configuration and restart', {template: 'configure-instance.js.j2', needsConfig: true}, ({calls, error}) => {
  assert.ifError(error);
  const configurations = calls.filter(c => c[0] === 'configure');
  assert.equal(configurations.length, 1);
  assert.equal(configurations[0][1], calls.find(c => c[0] === 'check-config')[1]);
  assert.equal(configurations[0][2].restart, true);
});
check('router accounts are restricted to client IPs', {template: 'router-accounts.js.j2'}, ({calls, error}) => {
  assert.ifError(error);
  assert.deepEqual(calls.filter(c => c[0] === 'router').map(c => c[1]), ['router@10.10.20.21', 'router@10.20.20.21']);
});
check('existing router accounts request updates', {template: 'router-accounts.js.j2', routerExists: true}, ({calls, error}) => {
  assert.ifError(error);
  assert.ok(calls.filter(c => c[0] === 'router').every(c => c[2].update === true));
});
check('explicit clone data-loss opt-in allows provisioning', {template: 'cluster-allow.js.j2', members: addresses.slice(0, 2), candidateData: 1}, ({calls, error}) => {
  assert.ifError(error);
  assert.equal(calls.filter(c => c[0] === 'add').length, 1);
});
check('string false never opts into data loss', {template: 'cluster-false-string.js.j2', members: addresses.slice(0, 2), candidateData: 1}, ({calls, error}) => {
  assert.ok(error);
  assert.equal(calls.filter(c => c[0] === 'add').length, 0);
});
check('clone opt-in cannot overwrite existing metadata', {template: 'cluster-allow.js.j2', members: addresses.slice(0, 2), candidateMetadata: 1}, ({calls, error}) => {
  assert.ok(error);
  assert.equal(calls.filter(c => c[0] === 'add').length, 0);
});
check('existing MYSQL cluster inspection succeeds', {template: 'cluster-inspect.js.j2'}, ({error}) => assert.ifError(error));
for (const options of [{stack: 'XCOM'}, {multi: true}, {noQuorum: true}, {replicaSet: true}]) {
  check('incompatible cluster inspection is refused ' + JSON.stringify(options), {template: 'cluster-inspect.js.j2', ...options}, ({error}) => assert.ok(error));
}
console.log(passed + ' scenarios passed');

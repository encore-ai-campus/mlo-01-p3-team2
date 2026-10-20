// mysqlsh의 실제 파일로 실행한다. 비밀번호는 root 전용 JSON에서만 읽는다.
function recoverCluster(config, api, checkOnly) {
  var expected = config.nodes.map(function (n) { return n.host + ':' + config.port; }).sort();
  if (config.nodes.length !== 3 || new Set(expected).size !== 3) throw new Error('INVALID_INVENTORY');
  var sessions = [];
  function connection(node) {
    return {scheme: 'mysql', host: node.host, port: config.port,
      user: config.user, password: config.password, 'connect-timeout': 8000};
  }
  function same(a, b) { return JSON.stringify(a.slice().sort()) === JSON.stringify(b.slice().sort()); }
  function snapshot(node, session) {
    var row = session.runSql('SELECT @@server_uuid, @@global.gtid_executed, ' +
      '@@global.group_replication_group_name, @@global.group_replication_communication_stack, ' +
      '@@global.group_replication_single_primary_mode, @@global.super_read_only, @@datadir, @@global.gtid_purged').fetchOne();
    if (row[0] !== node.uuid || row[2] !== config.groupUuid || row[3] !== 'MYSQL' ||
        Number(row[4]) !== 1 || row[6] !== '/var/lib/mysql/') throw new Error('SERVER_IDENTITY_MISMATCH ' + node.host);
    var clusters = session.runSql('SELECT cluster_id, cluster_name, cluster_type FROM mysql_innodb_cluster_metadata.clusters').fetchAll();
    if (clusters.length !== 1 || clusters[0][0] !== config.clusterId ||
        clusters[0][1] !== config.clusterName || clusters[0][2] !== 'gr') throw new Error('METADATA_MISMATCH ' + node.host);
    var members = session.runSql("SELECT mysql_server_uuid, addresses->>'$.mysqlClassic' FROM mysql_innodb_cluster_metadata.instances WHERE cluster_id = ?", [config.clusterId]).fetchAll();
    if (!same(members.map(function (r) { return r[0] + '@' + r[1]; }),
      config.nodes.map(function (n) { return n.uuid + '@' + n.host + ':' + config.port; }))) throw new Error('MEMBERSHIP_MISMATCH ' + node.host);
    var states = session.runSql('SELECT MEMBER_ID, MEMBER_STATE, MEMBER_ROLE FROM performance_schema.replication_group_members').fetchAll();
    return {node: node, gtid: row[1], purged: row[7], readOnly: Number(row[5]) === 1, states: states};
  }
  function allOffline(states) {
    // ERROR/RECOVERING도 자동 강제 처리하지 않는다. 다음 검사 또는 운영자 점검을 기다린다.
    return states.every(function (s) {
      return s.readOnly && s.states.length === 1 && s.states[0][0] === s.node.uuid && s.states[0][1] === 'OFFLINE';
    });
  }
  function validateHealthy(cluster) {
    var state = cluster.status().defaultReplicaSet;
    if (state.status !== 'OK' || state.topologyMode !== 'Single-Primary' ||
        !same(Object.keys(state.topology), expected)) throw new Error('CLUSTER_NOT_FULLY_HEALTHY');
    var primary = 0;
    expected.forEach(function (address) {
      var member = state.topology[address];
      if (member.status !== 'ONLINE') throw new Error('MEMBER_NOT_ONLINE ' + address);
      if (member.memberRole === 'PRIMARY') primary++;
    });
    if (primary !== 1 || expected.indexOf(state.primary) < 0) throw new Error('PRIMARY_NOT_UNIQUE');
  }
  try {
    config.nodes.forEach(function (node) { sessions.push(api.mysql.getSession(connection(node))); });
    var states = config.nodes.map(function (node, i) { return snapshot(node, sessions[i]); });
    if (!allOffline(states)) {
      // 정상 클러스터는 확인만 한다. 일부 장애와 정족수 상실에는 복구 API를 호출하지 않는다.
      var online = states.filter(function (s) { return s.states.some(function (r) { return r[0] === s.node.uuid && r[1] === 'ONLINE'; }); });
      if (!online.length) throw new Error('NOT_A_COMPLETE_OFFLINE_OUTAGE');
      api.shell.connect(connection(online[0].node));
      validateHealthy(api.dba.getCluster(config.clusterName));
      api.log('HEALTHY: 3 ONLINE, 1 PRIMARY; no changes');
      return 'healthy';
    }
    // GTID 문자열 길이가 아니라 MySQL의 집합 포함 관계로 최신 서버를 선택한다.
    var candidates = states.filter(function (candidate) {
      return states.every(function (other) {
        return Number(sessions[0].runSql('SELECT GTID_SUBSET(?, ?)', [other.gtid, candidate.gtid]).fetchOne()[0]) === 1;
      });
    });
    if (!candidates.length) throw new Error('DIVERGENT_GTID: manual investigation required');
    // 증분 복구에 필요한 로그가 이미 삭제됐다면 clone으로 넘어가지 않고 중단한다.
    if (states.some(function (other) {
      return Number(sessions[0].runSql('SELECT GTID_SUBSET(?, ?)', [candidates[0].purged, other.gtid]).fetchOne()[0]) !== 1;
    })) throw new Error('MISSING_BINLOG: incremental recovery cannot be guaranteed');
    var seed = candidates[0].node;
    api.shell.connect(connection(seed));
    api.dba.rebootClusterFromCompleteOutage(config.clusterName, {dryRun: true});
    api.log('DRY_RUN_OK: seed=' + seed.host);
    if (checkOnly) return 'dry-run';
    // 검증 중 상태/데이터가 변하면 이번 실행에서는 재부트하지 않는다.
    var fresh = config.nodes.map(function (node, i) { return snapshot(node, sessions[i]); });
    if (!allOffline(fresh) || fresh.some(function (s, i) { return s.gtid !== states[i].gtid || s.purged !== states[i].purged; })) throw new Error('STATE_CHANGED_DURING_CHECK');
    var cluster = api.dba.rebootClusterFromCompleteOutage(config.clusterName);
    validateHealthy(cluster);
    api.log('RECOVERED: 3 ONLINE, 1 PRIMARY; seed=' + seed.host);
    return 'recovered';
  } finally {
    sessions.forEach(function (session) { try { session.close(); } catch (_) {} });
  }
}

if (typeof mysql !== 'undefined' && typeof shell !== 'undefined') {
  var config = JSON.parse(os.loadTextFile('/etc/mysql-cluster-recovery/config.json'));
  try {
    recoverCluster(config, {mysql: mysql, shell: shell, dba: dba, log: function (message) { print(message + '\n'); }},
      os.getenv('MYSQL_RECOVERY_CHECK_ONLY') === '1');
  } catch (error) {
    // 라이브러리 오류에도 비밀번호가 출력되지 않도록 방어한다.
    var message = String(error.message || error);
    [config.password, encodeURIComponent(config.password)].forEach(function (secret) {
      if (secret) message = message.split(secret).join('[REDACTED]');
    });
    print('RECOVERY_REFUSED: ' + message);
    throw new Error('Recovery failed; see sanitized RECOVERY_REFUSED message');
  }
} else {
  module.exports = {recoverCluster: recoverCluster};
}
